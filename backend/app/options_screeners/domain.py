from dataclasses import dataclass
import math
from typing import TypeVar

from app.schemas import (
    CashSecuredPutCandidate,
    CoveredCallCandidate,
    CreditSpreadCandidate,
    CreditSpreadScreenerFilters,
    CreditSpreadStrategy,
    OptionContractIdentity,
    OptionsScreenerFilters,
)

ScreenerCandidate = (
    CashSecuredPutCandidate | CoveredCallCandidate | CreditSpreadCandidate
)
CandidateType = TypeVar("CandidateType", bound=ScreenerCandidate)


@dataclass(frozen=True)
class SpreadPricing:
    net_bid: float
    net_ask: float
    midpoint: float


def midpoint(bid: float | None, ask: float | None) -> float | None:
    if not valid_market(bid, ask):
        return None
    return (bid + ask) / 2


def csp_annualized_return(
    mid_credit: float | None,
    strike: float | None,
    dte: int | None,
) -> float | None:
    if not positive_finite(mid_credit, strike) or not positive_dte(dte):
        return None
    return (mid_credit / strike) * (365 / dte) * 100


def cc_annualized_return(
    mid_credit: float | None,
    underlying_price: float | None,
    dte: int | None,
) -> float | None:
    if not positive_finite(mid_credit, underlying_price) or not positive_dte(dte):
        return None
    return (mid_credit / underlying_price) * (365 / dte) * 100


def credit_spread_annualized_return(
    net_midpoint_credit: float | None,
    spread_width: float | None,
    dte: int | None,
) -> float | None:
    if (
        not positive_finite(net_midpoint_credit, spread_width)
        or net_midpoint_credit >= spread_width
        or not positive_dte(dte)
    ):
        return None
    maximum_loss = spread_width - net_midpoint_credit
    return (net_midpoint_credit / maximum_loss) * (365 / dte) * 100


def csp_discount_percentage(
    underlying_price: float | None,
    strike: float | None,
) -> float | None:
    if not positive_finite(underlying_price, strike):
        return None
    return ((underlying_price - strike) / underlying_price) * 100


def cc_gain_percentage(
    underlying_price: float | None,
    strike: float | None,
) -> float | None:
    if not positive_finite(underlying_price, strike):
        return None
    return ((strike - underlying_price) / underlying_price) * 100


def credit_spread_distance_percentage(
    strategy: CreditSpreadStrategy,
    underlying_price: float | None,
    short_strike: float | None,
) -> float | None:
    if not positive_finite(underlying_price, short_strike):
        return None
    if strategy == "put_credit_spread":
        return ((underlying_price - short_strike) / underlying_price) * 100
    return ((short_strike - underlying_price) / underlying_price) * 100


def spread_pricing(
    short_bid: float | None,
    short_ask: float | None,
    long_bid: float | None,
    long_ask: float | None,
) -> SpreadPricing | None:
    if not valid_market(short_bid, short_ask) or not valid_market(long_bid, long_ask):
        return None
    net_bid = short_bid - long_ask
    net_ask = short_ask - long_bid
    if net_bid <= 0 or net_ask < net_bid:
        return None
    return SpreadPricing(
        net_bid=net_bid,
        net_ask=net_ask,
        midpoint=(net_bid + net_ask) / 2,
    )


def matches_filters(
    *,
    dte: int | None,
    delta: float | None,
    annualized_return: float | None,
    filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
) -> bool:
    if (
        dte is None
        or delta is None
        or annualized_return is None
        or not finite_values(delta, annualized_return)
    ):
        return False
    absolute_delta = abs(delta)
    return (
        filters.minimum_dte <= dte <= filters.maximum_dte
        and filters.minimum_absolute_delta
        <= absolute_delta
        <= filters.maximum_absolute_delta
        and annualized_return >= filters.minimum_annualized_return
    )


def build_csp_candidate(
    *,
    ticker: str,
    stock_price: float | None,
    strike: float | None,
    expiration: str,
    dte: int | None,
    delta: float | None,
    bid: float | None,
    ask: float | None,
    contract: OptionContractIdentity,
) -> CashSecuredPutCandidate | None:
    mid_credit = midpoint(bid, ask)
    annualized_return = csp_annualized_return(mid_credit, strike, dte)
    discount_percentage = csp_discount_percentage(stock_price, strike)
    if (
        annualized_return is None
        or discount_percentage is None
        or delta is None
        or not finite_values(delta)
        or bid is None
        or ask is None
        or strike is None
        or stock_price is None
        or dte is None
    ):
        return None
    return CashSecuredPutCandidate(
        ticker=ticker,
        annualized_return=annualized_return,
        stock_price=stock_price,
        strike=strike,
        expiration=expiration,
        dte=dte,
        delta=delta,
        bid=bid,
        ask=ask,
        discount_percentage=discount_percentage,
        contract=contract,
    )


def build_cc_candidate(
    *,
    ticker: str,
    stock_price: float | None,
    strike: float | None,
    expiration: str,
    dte: int | None,
    delta: float | None,
    bid: float | None,
    ask: float | None,
    contract: OptionContractIdentity,
) -> CoveredCallCandidate | None:
    mid_credit = midpoint(bid, ask)
    annualized_return = cc_annualized_return(mid_credit, stock_price, dte)
    gain_percentage = cc_gain_percentage(stock_price, strike)
    if (
        annualized_return is None
        or gain_percentage is None
        or delta is None
        or not finite_values(delta)
        or bid is None
        or ask is None
        or strike is None
        or stock_price is None
        or dte is None
    ):
        return None
    return CoveredCallCandidate(
        ticker=ticker,
        annualized_return=annualized_return,
        stock_price=stock_price,
        strike=strike,
        expiration=expiration,
        dte=dte,
        delta=delta,
        bid=bid,
        ask=ask,
        gain_percentage=gain_percentage,
        contract=contract,
    )


def build_credit_spread_candidate(
    *,
    strategy: CreditSpreadStrategy,
    ticker: str,
    stock_price: float | None,
    short_strike: float | None,
    long_strike: float | None,
    expiration: str,
    dte: int | None,
    short_delta: float | None,
    short_bid: float | None,
    short_ask: float | None,
    long_bid: float | None,
    long_ask: float | None,
    short_contract: OptionContractIdentity,
    long_contract: OptionContractIdentity,
) -> CreditSpreadCandidate | None:
    if (
        short_strike is None
        or long_strike is None
        or not positive_finite(short_strike, long_strike)
    ):
        return None
    width = abs(short_strike - long_strike)
    pricing = spread_pricing(short_bid, short_ask, long_bid, long_ask)
    annualized_return = credit_spread_annualized_return(
        pricing.midpoint if pricing else None,
        width,
        dte,
    )
    distance_percentage = credit_spread_distance_percentage(
        strategy,
        stock_price,
        short_strike,
    )
    if (
        pricing is None
        or annualized_return is None
        or distance_percentage is None
        or short_delta is None
        or not finite_values(short_delta)
        or stock_price is None
        or dte is None
    ):
        return None
    return CreditSpreadCandidate(
        strategy=strategy,
        ticker=ticker,
        annualized_return=annualized_return,
        stock_price=stock_price,
        short_strike=short_strike,
        long_strike=long_strike,
        expiration=expiration,
        dte=dte,
        short_delta=short_delta,
        net_bid=pricing.net_bid,
        net_ask=pricing.net_ask,
        distance_percentage=distance_percentage,
        short_contract=short_contract,
        long_contract=long_contract,
    )


def sort_candidates(candidates: list[CandidateType]) -> list[CandidateType]:
    return sorted(candidates, key=candidate_sort_key)


def candidate_sort_key(candidate: ScreenerCandidate) -> tuple[object, ...]:
    if isinstance(candidate, CreditSpreadCandidate):
        strikes = (candidate.short_strike, candidate.long_strike)
    else:
        strikes = (candidate.strike, 0.0)
    return (
        -candidate.annualized_return,
        candidate.dte,
        candidate.ticker,
        candidate.expiration,
        *strikes,
    )


def valid_market(bid: float | None, ask: float | None) -> bool:
    return (
        bid is not None
        and ask is not None
        and finite_values(bid, ask)
        and bid >= 0
        and ask >= bid
    )


def positive_finite(*values: float | None) -> bool:
    return all(
        value is not None and math.isfinite(value) and value > 0
        for value in values
    )


def finite_values(*values: float) -> bool:
    return all(math.isfinite(value) for value in values)


def positive_dte(dte: int | None) -> bool:
    return dte is not None and dte > 0
