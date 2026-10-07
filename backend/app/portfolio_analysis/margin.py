"""Reg T maintenance margin estimate per strategy group, and margin-call distance.

Amounts are in the group's local currency per the whole group. Option
prices are per share, so contract amounts use the 100 multiplier. The model
is calibrated against IB's reported maintenance margin at no shock and is
only scaled up (house margin), never down.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.portfolio_analysis.pairing import STANDARD_OPTION_MULTIPLIER, GroupKind
from app.portfolio_analysis.pricing import OptionRight

LONG_STOCK_RATE = 0.25
# Not in the phase's rule list; Reg T's 30% short-stock maintenance.
SHORT_STOCK_RATE = 0.30
NAKED_RATE = 0.20
NAKED_MINIMUM_RATE = 0.10
BISECTION_STEPS = 40

ZERO_MARGIN_KINDS: frozenset[GroupKind] = frozenset(
    {"long_call", "long_put", "put_debit_spread", "call_debit_spread", "pmcc"}
)


@dataclass(frozen=True)
class MarginLeg:
    """One leg at its (stressed) price; `right` is None for stock."""

    right: OptionRight | None
    quantity: float
    price: float
    strike: float = 0.0


def group_margin(kind: GroupKind, legs: Sequence[MarginLeg], spot: float) -> float:
    """Reg T maintenance margin for one strategy group at underlying price `spot`."""
    if kind in ZERO_MARGIN_KINDS:
        return 0.0
    stock = [leg for leg in legs if leg.right is None]
    if kind in ("stock", "covered_call"):
        return sum(stock_margin(leg.quantity, leg.price) for leg in stock)

    options = [leg for leg in legs if leg.right is not None]
    shorts = [leg for leg in options if leg.quantity < 0]
    longs = [leg for leg in options if leg.quantity > 0]
    if not shorts:
        return 0.0
    short = shorts[0]
    contracts = abs(short.quantity) * STANDARD_OPTION_MULTIPLIER

    if kind == "short_put":
        return naked_put_margin(spot, short.strike, short.price) * contracts
    if kind == "naked_call":
        return naked_call_margin(spot, short.strike, short.price) * contracts
    if not longs:
        return 0.0
    long = longs[0]
    if kind in ("put_credit_spread", "call_credit_spread"):
        return abs(short.strike - long.strike) * contracts
    if kind == "pmcp":
        return max(0.0, short.strike - long.strike) * contracts
    raise ValueError(f"No margin rule for {kind!r}.")


def stock_margin(quantity: float, price: float) -> float:
    rate = LONG_STOCK_RATE if quantity >= 0 else SHORT_STOCK_RATE
    return rate * abs(quantity) * price


def naked_put_margin(spot: float, strike: float, premium: float) -> float:
    """Per share: max(20% x S - OTM amount, 10% x K) + premium."""
    out_of_the_money = max(0.0, spot - strike)
    return max(NAKED_RATE * spot - out_of_the_money, NAKED_MINIMUM_RATE * strike) + premium


def naked_call_margin(spot: float, strike: float, premium: float) -> float:
    """Per share: max(20% x S - OTM amount, 10% x S) + premium."""
    out_of_the_money = max(0.0, strike - spot)
    return max(NAKED_RATE * spot - out_of_the_money, NAKED_MINIMUM_RATE * spot) + premium


def calibration_factor(ib_margin: float | None, model_margin: float) -> float:
    """Scale the model up to IB's house margin; never below 1."""
    if ib_margin is None or model_margin <= 0:
        return 1.0
    return max(1.0, ib_margin / model_margin)


def distance_to_margin_call(
    excess_liquidity: Callable[[float, float], float],
    path: Sequence[tuple[float, float]],
) -> float | None:
    """SPY drop (as a positive fraction) at which excess liquidity reaches zero.

    Walks the path from no shock through each (SPY move, IV shock) point and
    bisects the first segment that crosses zero, moving both shocks together.
    Returns None when excess liquidity stays positive along the whole path.
    """
    start = (0.0, 0.0)
    if excess_liquidity(*start) <= 0:
        return 0.0
    for end in path:
        if excess_liquidity(*end) <= 0:
            low, high = 0.0, 1.0
            for _ in range(BISECTION_STEPS):
                middle = (low + high) / 2
                if excess_liquidity(*_between(start, end, middle)) <= 0:
                    high = middle
                else:
                    low = middle
            return -_between(start, end, high)[0]
        start = end
    return None


def _between(
    start: tuple[float, float],
    end: tuple[float, float],
    fraction: float,
) -> tuple[float, float]:
    return (
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
    )
