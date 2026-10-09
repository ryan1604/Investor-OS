"""Instantaneous price and volatility stress of an account's analysed legs.

Each underlying moves by beta x the SPY move, floored at -95%. Each option's
IV rises by the relative shock scaled by max(beta, 0.5), with puts getting
1.2x. Options are repriced with Black-Scholes at their current time to
expiry (no decay); stock P&L is linear. P&L is measured against the model
value at no shock, so the 0/0 cell is zero by construction. A strategy group
with a leg lacking a price, underlying price or IV is left out whole, so a
spread is never stressed as a naked leg; its legs are counted as excluded.
Each cell also carries stressed excess liquidity: stressed net liquidation
minus the calibrated Reg T model margin (see `margin.py`).
"""

from dataclasses import dataclass, replace
from datetime import datetime

from app.portfolio.domain import percent
from app.portfolio_analysis.exposure import years_to_expiry
from app.portfolio_analysis.margin import (
    MarginLeg,
    calibration_factor,
    distance_to_margin_call,
    group_margin,
)
from app.portfolio_analysis.pairing import STANDARD_OPTION_MULTIPLIER, GroupKind
from app.portfolio_analysis.pricing import OptionRight, black_scholes
from app.schemas import (
    AnalysisLeg,
    AnalysisMarginEstimate,
    AnalysisStressCell,
    AnalysisStressGrid,
    AnalysisUnderlying,
)

SPY_MOVES = (-0.30, -0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10)
IV_SHOCKS = (0.0, 0.25, 0.50, 1.00)
# (SPY move, IV shock) points of the highlighted realistic path.
REALISTIC_PATH = ((-0.05, 0.15), (-0.10, 0.40), (-0.20, 0.80), (-0.30, 1.00))
UNDERLYING_MOVE_FLOOR = -0.95
MIN_IV_SHOCK_BETA = 0.5
PUT_IV_SHOCK_MULTIPLIER = 1.2


@dataclass(frozen=True)
class StressLeg:
    """One leg ready to reprice; `right` is None for stock."""

    right: OptionRight | None
    quantity: float
    spot: float
    beta: float
    fx_rate: float
    strike: float = 0.0
    years: float = 0.0
    volatility: float = 0.0
    base_value: float = 0.0

    def value(self, spy_move: float, iv_shock: float, rate: float) -> float:
        """Per-share (or per-option-share) value in local currency after the shock."""
        spot = shocked_spot(self.spot, self.beta, spy_move)
        if self.right is None:
            return spot
        volatility = shocked_volatility(self.volatility, self.right, self.beta, iv_shock)
        return black_scholes(self.right, spot, self.strike, self.years, volatility, rate).price


def shocked_spot(spot: float, beta: float, spy_move: float) -> float:
    return spot * (1.0 + max(beta * spy_move, UNDERLYING_MOVE_FLOOR))


def shocked_volatility(volatility: float, right: OptionRight, beta: float, iv_shock: float) -> float:
    shock = iv_shock * max(beta, MIN_IV_SHOCK_BETA)
    if right == "P":
        shock *= PUT_IV_SHOCK_MULTIPLIER
    return volatility * (1.0 + shock)


def stress_leg(leg: AnalysisLeg, beta: float, *, now: datetime, rate: float) -> StressLeg | None:
    """Prepare one analysed leg for repricing, or None without a price, spot or IV."""
    if leg.sec_type == "STK":
        if leg.price is None:
            return None
        return StressLeg(
            right=None,
            quantity=leg.quantity,
            spot=leg.price,
            beta=beta,
            fx_rate=leg.fx_rate,
            base_value=leg.price,
        )
    if (
        leg.right not in ("C", "P")
        or not leg.strike
        or not leg.underlying_price
        or leg.implied_volatility is None
    ):
        return None
    option = StressLeg(
        right=leg.right,
        quantity=leg.quantity,
        spot=leg.underlying_price,
        beta=beta,
        fx_rate=leg.fx_rate,
        strike=leg.strike,
        years=years_to_expiry(leg.expiry or "", now),
        volatility=leg.implied_volatility,
    )
    return replace(option, base_value=option.value(0.0, 0.0, rate))


@dataclass(frozen=True)
class StressGroup:
    """A strategy group's repriceable legs; `complete` is False if any leg can't be priced."""

    kind: GroupKind
    legs: tuple[StressLeg, ...]
    complete: bool

    def pnl_and_margin(self, spy_move: float, iv_shock: float, rate: float) -> tuple[float, float]:
        """USD P&L and model margin after the shock; an incomplete group adds neither."""
        if not self.complete or not self.legs:
            return 0.0, 0.0
        pnl = 0.0
        margin_legs = []
        for leg in self.legs:
            value = leg.value(spy_move, iv_shock, rate)
            multiplier = 1.0 if leg.right is None else STANDARD_OPTION_MULTIPLIER
            pnl += (value - leg.base_value) * multiplier * leg.quantity * leg.fx_rate
            margin_legs.append(MarginLeg(leg.right, leg.quantity, value, leg.strike))
        first = self.legs[0]
        spot = shocked_spot(first.spot, first.beta, spy_move)
        return pnl, group_margin(self.kind, margin_legs, spot) * first.fx_rate


def stress_groups(
    underlyings: list[AnalysisUnderlying],
    *,
    now: datetime,
    risk_free_rate: float,
) -> list[StressGroup]:
    groups = []
    for underlying in underlyings:
        for group in underlying.groups:
            legs = [
                stress_leg(leg, underlying.beta, now=now, rate=risk_free_rate)
                for leg in group.legs
            ]
            groups.append(
                StressGroup(
                    kind=group.kind,
                    legs=tuple(leg for leg in legs if leg is not None),
                    complete=all(leg is not None for leg in legs),
                )
            )
    return groups


def stressed_legs(groups: list[StressGroup]) -> list[StressLeg]:
    return [leg for group in groups if group.complete for leg in group.legs]


def leg_count(underlyings: list[AnalysisUnderlying]) -> int:
    return sum(len(group.legs) for underlying in underlyings for group in underlying.groups)


def scenario(
    groups: list[StressGroup],
    spy_move: float,
    iv_shock: float,
    rate: float,
) -> tuple[float, float]:
    """Total USD P&L and model margin for one shock."""
    pnl = margin = 0.0
    for group in groups:
        group_pnl, group_margin_value = group.pnl_and_margin(spy_move, iv_shock, rate)
        pnl += group_pnl
        margin += group_margin_value
    return pnl, margin


def build_stress_grid(
    underlyings: list[AnalysisUnderlying],
    net_liquidation: float | None,
    ib_maintenance_margin: float | None,
    *,
    now: datetime,
    risk_free_rate: float,
) -> AnalysisStressGrid:
    groups = stress_groups(underlyings, now=now, risk_free_rate=risk_free_rate)
    _, model_margin = scenario(groups, 0.0, 0.0, risk_free_rate)
    factor = calibration_factor(ib_maintenance_margin, model_margin)
    path_points = set(REALISTIC_PATH)

    def excess_liquidity(pnl: float, margin: float) -> float | None:
        if net_liquidation is None:
            return None
        return net_liquidation + pnl - factor * margin

    def cell(spy_move: float, iv_shock: float) -> AnalysisStressCell:
        pnl, margin = scenario(groups, spy_move, iv_shock, risk_free_rate)
        return AnalysisStressCell(
            spy_move_percent=spy_move * 100,
            iv_shock_percent=iv_shock * 100,
            pnl=pnl,
            pnl_percent=percent(pnl, net_liquidation),
            excess_liquidity=excess_liquidity(pnl, margin),
            realistic_path=(spy_move, iv_shock) in path_points,
        )

    distance = None
    if net_liquidation is not None:
        distance = distance_to_margin_call(
            lambda move, shock: excess_liquidity(*scenario(groups, move, shock, risk_free_rate)),
            REALISTIC_PATH,
        )
    legs = len(stressed_legs(groups))
    return AnalysisStressGrid(
        spy_moves_percent=[move * 100 for move in SPY_MOVES],
        iv_shocks_percent=[shock * 100 for shock in IV_SHOCKS],
        cells=[cell(move, shock) for move in SPY_MOVES for shock in IV_SHOCKS],
        realistic_path=[cell(move, shock) for move, shock in REALISTIC_PATH],
        legs=legs,
        excluded_legs=leg_count(underlyings) - legs,
        margin=AnalysisMarginEstimate(
            model_margin=model_margin,
            ib_maintenance_margin=ib_maintenance_margin,
            calibration_factor=factor,
            excluded_groups=sum(1 for group in groups if not group.complete),
            distance_to_margin_call_percent=None if distance is None else distance * 100,
            margin_call_beyond_path=net_liquidation is not None and distance is None,
        ),
    )
