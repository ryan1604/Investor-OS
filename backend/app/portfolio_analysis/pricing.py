"""Black-Scholes pricing and implied volatility for European equity options.

Greeks use IB's per-share conventions so model values can stand in for
`tickOptionComputation` values: theta is per calendar day and vega is per
1 IV point (0.01). Dividends are ignored, so American options, especially
deep ITM puts, are only approximated.
"""

import math
from dataclasses import dataclass
from typing import Literal

OptionRight = Literal["C", "P"]

DAYS_PER_YEAR = 365.0
MIN_IV = 1e-6
MAX_IV = 5.0
IV_PRICE_TOLERANCE = 1e-8
IV_MAX_ITERATIONS = 100


@dataclass(frozen=True)
class OptionValuation:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float


def norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes(
    right: OptionRight,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    rate: float,
) -> OptionValuation:
    """Price one option share; expired or zero-IV inputs return intrinsic values."""
    if right not in ("C", "P"):
        raise ValueError(f"Unsupported option right: {right!r}")
    if spot <= 0 or strike <= 0:
        raise ValueError("Spot and strike must be positive.")

    if years <= 0:
        return _expired_valuation(right, spot, strike)

    discount = math.exp(-rate * years)
    if volatility <= 0:
        return _zero_volatility_valuation(right, spot, strike, discount, rate)

    root_years = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility**2) * years) / (
        volatility * root_years
    )
    d2 = d1 - volatility * root_years
    density = norm_pdf(d1)
    gamma = density / (spot * volatility * root_years)
    vega = spot * density * root_years / 100.0
    decay = -spot * density * volatility / (2.0 * root_years)

    if right == "C":
        price = spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
        delta = norm_cdf(d1)
        theta = decay - rate * strike * discount * norm_cdf(d2)
    else:
        price = strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)
        delta = norm_cdf(d1) - 1.0
        theta = decay + rate * strike * discount * norm_cdf(-d2)

    return OptionValuation(
        price=max(price, 0.0),
        delta=delta,
        gamma=gamma,
        theta=theta / DAYS_PER_YEAR,
        vega=vega,
    )


def implied_volatility(
    right: OptionRight,
    price: float,
    spot: float,
    strike: float,
    years: float,
    rate: float,
) -> float | None:
    """Solve IV from an option price, or None when no volatility fits."""
    if years <= 0 or price <= 0 or spot <= 0 or strike <= 0:
        return None
    if price < intrinsic_value(right, spot, strike):
        return None

    def price_error(volatility: float) -> float:
        return black_scholes(right, spot, strike, years, volatility, rate).price - price

    low, high = MIN_IV, MAX_IV
    if price_error(high) < 0:
        return None
    if price_error(low) >= 0:
        # At or above intrinsic but at or below the zero-volatility value, which for a
        # call is S - K*e^(-rT): a deep ITM quote under the European bound.
        return MIN_IV

    volatility = 0.3
    for _ in range(IV_MAX_ITERATIONS):
        valuation = black_scholes(right, spot, strike, years, volatility, rate)
        error = valuation.price - price
        if abs(error) < IV_PRICE_TOLERANCE:
            return volatility
        if error > 0:
            high = volatility
        else:
            low = volatility

        vega_per_unit = valuation.vega * 100.0
        candidate = volatility - error / vega_per_unit if vega_per_unit > 1e-12 else low
        if not low < candidate < high:
            candidate = 0.5 * (low + high)
        volatility = candidate
        if high - low < 1e-12:
            return volatility

    return None


def intrinsic_value(right: OptionRight, spot: float, strike: float) -> float:
    return max(spot - strike, 0.0) if right == "C" else max(strike - spot, 0.0)


def _expired_valuation(right: OptionRight, spot: float, strike: float) -> OptionValuation:
    if spot == strike:
        delta = 0.5 if right == "C" else -0.5
    elif right == "C":
        delta = 1.0 if spot > strike else 0.0
    else:
        delta = -1.0 if spot < strike else 0.0

    return OptionValuation(
        price=intrinsic_value(right, spot, strike),
        delta=delta,
        gamma=0.0,
        theta=0.0,
        vega=0.0,
    )


def _zero_volatility_valuation(
    right: OptionRight,
    spot: float,
    strike: float,
    discount: float,
    rate: float,
) -> OptionValuation:
    present_strike = strike * discount
    call_in_money = spot > present_strike
    if right == "C":
        price = max(spot - present_strike, 0.0)
        delta = 1.0 if call_in_money else 0.0
        theta = -rate * present_strike if call_in_money else 0.0
    else:
        price = max(present_strike - spot, 0.0)
        delta = -1.0 if spot < present_strike else 0.0
        theta = rate * present_strike if spot < present_strike else 0.0

    return OptionValuation(
        price=price,
        delta=delta,
        gamma=0.0,
        theta=theta / DAYS_PER_YEAR,
        vega=0.0,
    )
