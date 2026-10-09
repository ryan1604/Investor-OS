"""Option-adjusted exposure for one account, computed without IB access.

Units are USD. Dollar delta is delta x multiplier x quantity x underlying
price; gamma is the change in dollar delta for a 1% underlying move
(gamma x multiplier x quantity x price^2 / 100); theta is $ per day; vega
is $ per 1 IV point. Missing IB Greeks are filled from Black-Scholes at IB's
IV, or at an IV solved from the option's last or close price, or, without
either, from IB's position mark (an approved deviation for closed markets).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from app.ib.portfolio import AnalysisMarketData
from app.portfolio.domain import percent
from app.portfolio_analysis.beta import FALLBACK_BETA, ResolvedBeta
from app.portfolio_analysis.pairing import (
    STANDARD_OPTION_MULTIPLIER,
    StrategyGroup,
    is_supported_position,
    pair_strategies,
)
from app.portfolio_analysis.pricing import black_scholes, implied_volatility
from app.sessions import US_MARKET_TIME_ZONE
from app.schemas import (
    AnalysisCoverage,
    AnalysisExposure,
    AnalysisGreeksSource,
    AnalysisGroup,
    AnalysisLeg,
    AnalysisSummary,
    AnalysisUnderlying,
    AnalysisUnsupportedPosition,
    PortfolioAccountSummary,
    PortfolioPosition,
)

BASE_CURRENCY = "USD"
GREEK_KEYS = ("delta", "gamma", "theta", "vega")
SECONDS_PER_YEAR = 365 * 24 * 60 * 60


@dataclass(frozen=True)
class PositionMetrics:
    """Exposure for one long share or contract of a position, in USD."""

    per_unit: AnalysisExposure
    price: float | None
    underlying_price: float | None
    implied_volatility: float | None
    delta: float | None
    greeks_source: AnalysisGreeksSource | None
    fx_rate: float
    flags: tuple[str, ...]

    @property
    def missing_price(self) -> bool:
        return "missing_price" in self.flags


@dataclass
class AccountExposure:
    summary: AnalysisSummary
    underlyings: list[AnalysisUnderlying] = field(default_factory=list)
    unsupported: list[AnalysisUnsupportedPosition] = field(default_factory=list)


def build_account_exposure(
    account: str,
    positions: list[PortfolioPosition],
    account_summary: PortfolioAccountSummary | None,
    market: AnalysisMarketData,
    betas: dict[str, ResolvedBeta],
    *,
    now: datetime,
    risk_free_rate: float,
) -> AccountExposure:
    """Aggregate one account's positions per leg, strategy group, and underlying."""
    account_positions = [position for position in positions if position.account == account]
    rates = {BASE_CURRENCY: 1.0} | market.exchange_rates.get(account, {})
    stock_prices = underlying_prices(positions, market)

    supported: list[PortfolioPosition] = []
    unsupported: list[AnalysisUnsupportedPosition] = []
    for position in account_positions:
        reason = unsupported_reason(position, rates)
        if reason is None:
            supported.append(position)
        else:
            unsupported.append(unsupported_position(position, reason))

    metrics = {
        id(position): position_metrics(
            position,
            market,
            stock_prices,
            betas,
            fx_rate=rates[position.currency],
            now=now,
            risk_free_rate=risk_free_rate,
        )
        for position in supported
    }
    groups_by_symbol: dict[str, list[AnalysisGroup]] = defaultdict(list)
    for group in pair_strategies(supported):
        groups_by_symbol[group.symbol].append(analysis_group(group, metrics))

    net_liquidation = account_summary.net_liquidation if account_summary else None
    underlyings = [
        analysis_underlying(
            symbol,
            groups,
            betas.get(symbol),
            stock_prices.get(symbol),
            net_liquidation,
        )
        for symbol, groups in groups_by_symbol.items()
    ]
    underlyings.sort(key=lambda underlying: (-abs(underlying.beta_weighted_delta), underlying.symbol))

    coverage = AnalysisCoverage(
        positions=len(account_positions),
        fallback_greeks=sum(
            1 for value in metrics.values() if value.greeks_source not in (None, "ib")
        ),
        fallback_beta=sum(
            1 for position in supported if resolved_beta(betas, position.symbol).is_fallback
        ),
        unsupported=len(unsupported),
        fx_converted=sum(1 for value in metrics.values() if "fx_converted" in value.flags),
        missing_price=sum(1 for value in metrics.values() if value.missing_price),
    )
    return AccountExposure(
        summary=account_summary_metrics(underlyings, account_summary, coverage),
        underlyings=underlyings,
        unsupported=unsupported,
    )


def unsupported_reason(position: PortfolioPosition, rates: dict[str, float]) -> str | None:
    if not is_supported_position(position):
        return f"Unsupported instrument ({position.sec_type})."
    if position.currency not in rates:
        return f"No IB exchange rate for {position.currency}."
    return None


def unsupported_position(
    position: PortfolioPosition,
    reason: str,
) -> AnalysisUnsupportedPosition:
    return AnalysisUnsupportedPosition(
        con_id=position.con_id,
        symbol=position.symbol,
        sec_type=position.sec_type,
        local_symbol=position.local_symbol,
        currency=position.currency,
        quantity=position.quantity,
        reason=reason,
    )


def underlying_prices(
    positions: list[PortfolioPosition],
    market: AnalysisMarketData,
) -> dict[str, float]:
    """Price each underlying from held stock quotes, then underlying-only quotes."""
    prices: dict[str, float] = {}
    for symbol, values in market.underlyings.items():
        price = quote_price(values)
        if price is not None:
            prices[symbol] = price
    for position in positions:
        if position.sec_type != "STK":
            continue
        price = quote_price(market.by_con_id.get(position.con_id or 0, {})) or position.last_price
        if price is not None:
            prices[position.symbol] = price
    return prices


def quote_price(values: dict[str, float]) -> float | None:
    return values.get("last") or values.get("close")


def resolved_beta(betas: dict[str, ResolvedBeta], symbol: str) -> ResolvedBeta:
    return betas.get(symbol) or ResolvedBeta(symbol, FALLBACK_BETA, "fallback")


def position_metrics(
    position: PortfolioPosition,
    market: AnalysisMarketData,
    stock_prices: dict[str, float],
    betas: dict[str, ResolvedBeta],
    *,
    fx_rate: float,
    now: datetime,
    risk_free_rate: float,
) -> PositionMetrics:
    beta = resolved_beta(betas, position.symbol)
    flags = []
    if position.currency != BASE_CURRENCY:
        flags.append("fx_converted")
    if beta.is_fallback:
        flags.append("fallback_beta")
    values = market.by_con_id.get(position.con_id or 0, {})

    if position.sec_type == "STK":
        price = quote_price(values) or position.last_price or stock_prices.get(position.symbol)
        if price is None:
            flags.append("missing_price")
        dollar_delta = price * fx_rate if price is not None else 0.0
        return PositionMetrics(
            per_unit=AnalysisExposure(
                dollar_delta=dollar_delta,
                beta_weighted_delta=dollar_delta * beta.beta,
            ),
            price=price,
            underlying_price=price,
            implied_volatility=None,
            delta=1.0,
            greeks_source=None,
            fx_rate=fx_rate,
            flags=tuple(flags),
        )

    spot = stock_prices.get(position.symbol) or values.get("underlying_price")
    option_price = quote_price(values) or position.last_price
    from_mark = option_price is None
    if from_mark:
        option_price = position_mark(position)
    greeks, volatility, source = hybrid_greeks(
        position,
        values,
        spot,
        option_price,
        now=now,
        risk_free_rate=risk_free_rate,
    )
    if source == "fallback":
        flags.append("fallback_greeks")
    elif source == "solved_iv":
        flags.append("solved_iv")
        if from_mark:
            flags.append("mark_price")
    elif source == "missing":
        flags.append("missing_greeks")
    if spot is None:
        flags.append("missing_price")

    scale = STANDARD_OPTION_MULTIPLIER * fx_rate
    delta = greeks.get("delta")
    dollar_delta = delta * scale * spot if delta is not None and spot is not None else 0.0
    gamma = greeks.get("gamma")
    return PositionMetrics(
        per_unit=AnalysisExposure(
            dollar_delta=dollar_delta,
            beta_weighted_delta=dollar_delta * beta.beta,
            gamma=gamma * scale * spot**2 / 100 if gamma is not None and spot is not None else 0.0,
            theta=(greeks.get("theta") or 0.0) * scale,
            vega=(greeks.get("vega") or 0.0) * scale,
        ),
        price=option_price,
        underlying_price=spot,
        implied_volatility=volatility,
        delta=delta,
        greeks_source=source,
        fx_rate=fx_rate,
        flags=tuple(flags),
    )


def position_mark(position: PortfolioPosition) -> float | None:
    """IB's per-share mark from the P&L feed's position value, used only without quotes."""
    if not position.market_value or not position.quantity:
        return None
    mark = position.market_value / (position.quantity * STANDARD_OPTION_MULTIPLIER)
    return mark if mark > 0 else None


def hybrid_greeks(
    position: PortfolioPosition,
    values: dict[str, float],
    spot: float | None,
    option_price: float | None,
    *,
    now: datetime,
    risk_free_rate: float,
) -> tuple[dict[str, float], float | None, AnalysisGreeksSource]:
    """Use IB Greeks, filling any missing ones from Black-Scholes."""
    greeks = {key: values[key] for key in GREEK_KEYS if values.get(key) is not None}
    volatility = values.get("implied_volatility")
    if len(greeks) == len(GREEK_KEYS):
        return greeks, volatility, "ib"
    if spot is None:
        return greeks, volatility, "missing"

    right = position.right or "C"
    strike = position.strike or 0.0
    years = years_to_expiry(position.expiry or "", now)
    source: AnalysisGreeksSource = "fallback"
    if volatility is None and option_price is not None:
        volatility = implied_volatility(right, option_price, spot, strike, years, risk_free_rate)
        source = "solved_iv"
    if volatility is None:
        if years > 0:
            return greeks, None, "missing"
        volatility = 0.0

    model = black_scholes(right, spot, strike, years, volatility, risk_free_rate)
    model_values = {
        "delta": model.delta,
        "gamma": model.gamma,
        "theta": model.theta,
        "vega": model.vega,
    }
    return model_values | greeks, volatility, source


def years_to_expiry(expiry: str, now: datetime) -> float:
    """Years until 4 pm New York on the expiry date; negative once expired."""
    try:
        expiry_date = datetime.strptime(expiry[:8], "%Y%m%d")
    except ValueError:
        return 0.0
    expires_at = expiry_date.replace(hour=16, tzinfo=US_MARKET_TIME_ZONE)
    return (expires_at - now).total_seconds() / SECONDS_PER_YEAR


def analysis_group(
    group: StrategyGroup,
    metrics: dict[int, PositionMetrics],
) -> AnalysisGroup:
    legs = []
    for paired_leg in group.legs:
        position = paired_leg.position
        leg_metrics = metrics[id(position)]
        legs.append(
            AnalysisLeg(
                **scaled(leg_metrics.per_unit, paired_leg.quantity).model_dump(),
                con_id=position.con_id,
                symbol=position.symbol,
                sec_type=position.sec_type,
                local_symbol=position.local_symbol,
                right=position.right,
                strike=position.strike,
                expiry=position.expiry,
                currency=position.currency,
                quantity=paired_leg.quantity,
                price=leg_metrics.price,
                underlying_price=leg_metrics.underlying_price,
                implied_volatility=leg_metrics.implied_volatility,
                delta=leg_metrics.delta,
                greeks_source=leg_metrics.greeks_source,
                fx_rate=leg_metrics.fx_rate,
                flags=list(leg_metrics.flags),
            )
        )
    fx_rate = legs[0].fx_rate if legs else 1.0
    return AnalysisGroup(
        **summed(legs).model_dump(),
        kind=group.kind,
        label=group.label,
        quantity=group.quantity,
        premium_type=group.premium_type,
        net_premium=None if group.net_premium is None else group.net_premium * fx_rate,
        max_loss=None if group.max_loss is None else group.max_loss * fx_rate,
        assignment_exposure=group.assignment_exposure * fx_rate,
        legs=legs,
    )


def analysis_underlying(
    symbol: str,
    groups: list[AnalysisGroup],
    beta: ResolvedBeta | None,
    underlying_price: float | None,
    net_liquidation: float | None,
) -> AnalysisUnderlying:
    resolved = beta or ResolvedBeta(symbol, FALLBACK_BETA, "fallback")
    exposure = summed(groups)
    unlimited = any(group.max_loss is None for group in groups)
    return AnalysisUnderlying(
        **exposure.model_dump(),
        symbol=symbol,
        beta=resolved.beta,
        beta_source=resolved.source,
        beta_observations=resolved.observations,
        underlying_price=underlying_price,
        net_liquidation_percent=abs_percent(exposure.dollar_delta, net_liquidation),
        max_loss=None if unlimited else sum(group.max_loss or 0.0 for group in groups),
        max_loss_unlimited=unlimited,
        assignment_exposure=sum(group.assignment_exposure for group in groups),
        groups=groups,
    )


def account_summary_metrics(
    underlyings: list[AnalysisUnderlying],
    account_summary: PortfolioAccountSummary | None,
    coverage: AnalysisCoverage,
) -> AnalysisSummary:
    net_liquidation = account_summary.net_liquidation if account_summary else None
    maintenance_margin = account_summary.maintenance_margin if account_summary else None
    exposure = summed(underlyings)
    assignment_exposure = sum(underlying.assignment_exposure for underlying in underlyings)
    largest = max(underlyings, key=lambda underlying: abs(underlying.dollar_delta), default=None)
    return AnalysisSummary(
        net_liquidation=net_liquidation,
        gross_dollar_delta=sum(abs(underlying.dollar_delta) for underlying in underlyings),
        net_dollar_delta=exposure.dollar_delta,
        beta_weighted_delta=exposure.beta_weighted_delta,
        beta_weighted_delta_multiple=(
            exposure.beta_weighted_delta / net_liquidation if net_liquidation else None
        ),
        net_gamma=exposure.gamma,
        net_theta=exposure.theta,
        net_vega=exposure.vega,
        assignment_exposure=assignment_exposure,
        assignment_exposure_percent=percent(assignment_exposure, net_liquidation),
        maintenance_margin=maintenance_margin,
        margin_utilisation_percent=percent(maintenance_margin, net_liquidation),
        excess_liquidity=account_summary.excess_liquidity if account_summary else None,
        largest_underlying=largest.symbol if largest else None,
        largest_underlying_percent=(
            abs_percent(largest.dollar_delta, net_liquidation) if largest else None
        ),
        coverage=coverage,
    )


def scaled(exposure: AnalysisExposure, quantity: float) -> AnalysisExposure:
    return AnalysisExposure(
        dollar_delta=exposure.dollar_delta * quantity,
        beta_weighted_delta=exposure.beta_weighted_delta * quantity,
        gamma=exposure.gamma * quantity,
        theta=exposure.theta * quantity,
        vega=exposure.vega * quantity,
    )


def summed(items: list[AnalysisExposure]) -> AnalysisExposure:
    return AnalysisExposure(
        dollar_delta=sum(item.dollar_delta for item in items),
        beta_weighted_delta=sum(item.beta_weighted_delta for item in items),
        gamma=sum(item.gamma for item in items),
        theta=sum(item.theta for item in items),
        vega=sum(item.vega for item in items),
    )


def abs_percent(value: float, net_liquidation: float | None) -> float | None:
    result = percent(value, net_liquidation)
    return abs(result) if result is not None else None
