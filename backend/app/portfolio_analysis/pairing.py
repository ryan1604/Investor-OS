"""Group stock and option legs into strategies for Portfolio Analysis.

Each short option leg is matched in this order: a same-expiry vertical
(nearest strike first), held shares (covered call), a long option with the
same or later expiry and the same or better strike (PMCC for calls, its
mirror image for puts), and otherwise it is left naked. Quantities split
across groups, so 3 short puts against 2 long puts form 2 spreads and 1
naked put. Dollar amounts assume IB's per-contract option average cost.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from app.schemas import PortfolioPosition

STANDARD_OPTION_MULTIPLIER = 100.0

GroupKind = Literal[
    "stock",
    "long_call",
    "long_put",
    "put_credit_spread",
    "call_credit_spread",
    "put_debit_spread",
    "call_debit_spread",
    "covered_call",
    "pmcc",
    "pmcp",
    "short_put",
    "naked_call",
]
PremiumType = Literal["credit", "debit"]

GROUP_LABELS: dict[GroupKind, str] = {
    "stock": "Stock",
    "long_call": "Long Call",
    "long_put": "Long Put",
    "put_credit_spread": "Put Credit Spread",
    "call_credit_spread": "Call Credit Spread",
    "put_debit_spread": "Put Debit Spread",
    "call_debit_spread": "Call Debit Spread",
    "covered_call": "Covered Call",
    "pmcc": "PMCC",
    "pmcp": "Poor Man's Covered Put",
    "short_put": "Cash-Secured / Naked Put",
    "naked_call": "Naked Call",
}


VERTICAL_KINDS: dict[tuple[str, bool], GroupKind] = {
    ("P", True): "put_credit_spread",
    ("C", True): "call_credit_spread",
    ("P", False): "put_debit_spread",
    ("C", False): "call_debit_spread",
}


@dataclass(frozen=True)
class PairedLeg:
    position: PortfolioPosition
    # Signed shares or contracts of the position assigned to this group.
    quantity: float


@dataclass(frozen=True)
class StrategyGroup:
    account: str
    symbol: str
    kind: GroupKind
    legs: tuple[PairedLeg, ...]
    # Spreads, contracts, or shares, always positive.
    quantity: float
    premium_type: PremiumType | None
    # Positive when premium was received; None for stock-only groups.
    net_premium: float | None
    # None means unlimited.
    max_loss: float | None
    assignment_exposure: float

    @property
    def label(self) -> str:
        return GROUP_LABELS[self.kind]


@dataclass
class _Leg:
    position: PortfolioPosition
    remaining: float = field(init=False)

    def __post_init__(self) -> None:
        self.remaining = abs(self.position.quantity)

    @property
    def strike(self) -> float:
        return self.position.strike or 0.0

    @property
    def expiry(self) -> str:
        return self.position.expiry or ""

    @property
    def right(self) -> str:
        return self.position.right or ""


def is_supported_position(position: PortfolioPosition) -> bool:
    """US stocks/ETFs and standard (100-multiplier) equity options only."""
    if position.sec_type == "STK":
        return True
    return (
        position.sec_type == "OPT"
        and position.right in ("C", "P")
        and bool(position.strike)
        and bool(position.expiry)
        and option_multiplier(position) == STANDARD_OPTION_MULTIPLIER
    )


def option_multiplier(position: PortfolioPosition) -> float | None:
    try:
        return float(position.multiplier) if position.multiplier else None
    except ValueError:
        return None


def pair_strategies(positions: list[PortfolioPosition]) -> list[StrategyGroup]:
    """Pair supported positions per account and underlying; others are ignored."""
    by_underlying: dict[tuple[str, str], list[PortfolioPosition]] = defaultdict(list)
    for position in positions:
        if position.quantity and is_supported_position(position):
            by_underlying[(position.account, position.symbol)].append(position)

    groups: list[StrategyGroup] = []
    for key in sorted(by_underlying):
        groups.extend(_pair_underlying(by_underlying[key]))
    return groups


def _pair_underlying(positions: list[PortfolioPosition]) -> list[StrategyGroup]:
    options = [position for position in positions if position.sec_type == "OPT"]
    shorts = sorted(
        (_Leg(position) for position in options if position.quantity < 0),
        key=lambda leg: (leg.expiry, leg.right, leg.strike),
    )
    longs = sorted(
        (_Leg(position) for position in options if position.quantity > 0),
        key=lambda leg: (leg.expiry, leg.right, leg.strike),
    )
    stocks = [_Leg(position) for position in positions if position.sec_type == "STK"]
    groups: list[StrategyGroup] = []

    _pair_verticals(shorts, longs, groups)
    _pair_covered_calls(shorts, stocks, groups)
    _pair_diagonals(shorts, longs, groups)

    for leg in shorts:
        if leg.remaining > 0:
            kind: GroupKind = "short_put" if leg.right == "P" else "naked_call"
            groups.append(_single_option_group(kind, leg, -leg.remaining))
    for leg in longs:
        if leg.remaining > 0:
            kind = "long_put" if leg.right == "P" else "long_call"
            groups.append(_single_option_group(kind, leg, leg.remaining))
    for leg in stocks:
        if leg.remaining > 0:
            groups.append(_stock_group(leg))
    return groups


def _pair_verticals(shorts: list[_Leg], longs: list[_Leg], groups: list[StrategyGroup]) -> None:
    # Nearest strikes pair first; on equal width, credit spreads win, then lower strikes.
    candidates = sorted(
        (
            abs(short.strike - long.strike),
            not _is_credit_vertical(short, long),
            short.strike,
            long.strike,
            short_index,
            long_index,
        )
        for short_index, short in enumerate(shorts)
        for long_index, long in enumerate(longs)
        if short.right == long.right
        and short.expiry == long.expiry
        and short.strike != long.strike
    )
    for *_, short_index, long_index in candidates:
        short, long = shorts[short_index], longs[long_index]
        quantity = min(short.remaining, long.remaining)
        if quantity <= 0:
            continue
        short.remaining -= quantity
        long.remaining -= quantity
        groups.append(_vertical_group(short, long, quantity))


def _pair_covered_calls(shorts: list[_Leg], stocks: list[_Leg], groups: list[StrategyGroup]) -> None:
    long_stock = next((leg for leg in stocks if leg.position.quantity > 0), None)
    if long_stock is None:
        return

    for short in shorts:
        if short.right != "C" or short.remaining <= 0:
            continue
        coverable = long_stock.remaining // STANDARD_OPTION_MULTIPLIER
        quantity = min(short.remaining, coverable)
        if quantity <= 0:
            return
        short.remaining -= quantity
        shares = quantity * STANDARD_OPTION_MULTIPLIER
        long_stock.remaining -= shares
        premium = _premium(short.position, quantity)
        stock_cost = (long_stock.position.average_cost or 0.0) * shares
        groups.append(
            StrategyGroup(
                account=short.position.account,
                symbol=short.position.symbol,
                kind="covered_call",
                legs=(
                    PairedLeg(long_stock.position, shares),
                    PairedLeg(short.position, -quantity),
                ),
                quantity=quantity,
                premium_type="credit",
                net_premium=premium,
                max_loss=max(0.0, stock_cost - premium),
                assignment_exposure=0.0,
            )
        )


def _pair_diagonals(shorts: list[_Leg], longs: list[_Leg], groups: list[StrategyGroup]) -> None:
    for short in shorts:
        eligible = sorted(
            (
                (long.expiry, abs(long.strike - short.strike), long_index)
                for long_index, long in enumerate(longs)
                if long.right == short.right
                and long.expiry >= short.expiry
                and _has_same_or_better_strike(short, long)
            )
        )
        for *_, long_index in eligible:
            if short.remaining <= 0:
                break
            long = longs[long_index]
            quantity = min(short.remaining, long.remaining)
            if quantity <= 0:
                continue
            short.remaining -= quantity
            long.remaining -= quantity
            net_premium = _premium(short.position, quantity) + _premium(long.position, -quantity)
            groups.append(
                StrategyGroup(
                    account=short.position.account,
                    symbol=short.position.symbol,
                    kind="pmcc" if short.right == "C" else "pmcp",
                    legs=(
                        PairedLeg(long.position, quantity),
                        PairedLeg(short.position, -quantity),
                    ),
                    quantity=quantity,
                    premium_type=_premium_type(net_premium),
                    net_premium=net_premium,
                    # The long leg is worth at least the short leg's intrinsic value.
                    max_loss=max(0.0, -net_premium),
                    assignment_exposure=0.0,
                )
            )


def _has_same_or_better_strike(short: _Leg, long: _Leg) -> bool:
    if short.right == "C":
        return long.strike <= short.strike
    return long.strike >= short.strike


def _is_credit_vertical(short: _Leg, long: _Leg) -> bool:
    # The short leg is closer to the money: higher strike for puts, lower for calls.
    if short.right == "P":
        return short.strike > long.strike
    return short.strike < long.strike


def _vertical_group(short: _Leg, long: _Leg, quantity: float) -> StrategyGroup:
    is_credit = _is_credit_vertical(short, long)
    kind = VERTICAL_KINDS[(short.right, is_credit)]
    net_premium = _premium(short.position, quantity) + _premium(long.position, -quantity)
    width = abs(short.strike - long.strike) * STANDARD_OPTION_MULTIPLIER * quantity
    max_loss = max(0.0, width - net_premium) if is_credit else max(0.0, -net_premium)
    return StrategyGroup(
        account=short.position.account,
        symbol=short.position.symbol,
        kind=kind,
        legs=(PairedLeg(short.position, -quantity), PairedLeg(long.position, quantity)),
        quantity=quantity,
        premium_type="credit" if is_credit else "debit",
        net_premium=net_premium,
        max_loss=max_loss,
        assignment_exposure=max_loss if kind == "put_credit_spread" else 0.0,
    )


def _single_option_group(kind: GroupKind, leg: _Leg, signed_quantity: float) -> StrategyGroup:
    quantity = abs(signed_quantity)
    net_premium = _premium(leg.position, -signed_quantity)
    if kind == "short_put":
        max_loss: float | None = max(
            0.0, leg.strike * STANDARD_OPTION_MULTIPLIER * quantity - net_premium
        )
        assignment_exposure = leg.strike * STANDARD_OPTION_MULTIPLIER * quantity
    elif kind == "naked_call":
        max_loss = None
        assignment_exposure = 0.0
    else:
        max_loss = max(0.0, -net_premium)
        assignment_exposure = 0.0
    return StrategyGroup(
        account=leg.position.account,
        symbol=leg.position.symbol,
        kind=kind,
        legs=(PairedLeg(leg.position, signed_quantity),),
        quantity=quantity,
        premium_type=_premium_type(net_premium) or ("debit" if signed_quantity > 0 else "credit"),
        net_premium=net_premium,
        max_loss=max_loss,
        assignment_exposure=assignment_exposure,
    )


def _stock_group(leg: _Leg) -> StrategyGroup:
    shares = leg.remaining if leg.position.quantity > 0 else -leg.remaining
    max_loss = (
        (leg.position.average_cost or 0.0) * shares if shares > 0 else None
    )
    return StrategyGroup(
        account=leg.position.account,
        symbol=leg.position.symbol,
        kind="stock",
        legs=(PairedLeg(leg.position, shares),),
        quantity=abs(shares),
        premium_type=None,
        net_premium=None,
        max_loss=max_loss,
        assignment_exposure=0.0,
    )


def _premium(position: PortfolioPosition, sold_quantity: float) -> float:
    """Premium received for selling sold_quantity contracts at the average cost."""
    return (position.average_cost or 0.0) * sold_quantity


def _premium_type(net_premium: float) -> PremiumType | None:
    if net_premium > 0:
        return "credit"
    if net_premium < 0:
        return "debit"
    return None
