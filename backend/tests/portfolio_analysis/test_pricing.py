import math

import pytest

from app.config import Settings
from app.portfolio_analysis.pricing import (
    MIN_IV,
    black_scholes,
    implied_volatility,
    intrinsic_value,
    norm_cdf,
)


def test_norm_cdf_reference_points():
    assert norm_cdf(0) == pytest.approx(0.5)
    assert norm_cdf(1.96) == pytest.approx(0.9750021, abs=1e-7)
    assert norm_cdf(-1.0) == pytest.approx(0.1586553, abs=1e-7)


def test_prices_match_hull_reference_values():
    # Hull, Options Futures and Other Derivatives: S=42, K=40, r=10%, sigma=20%, T=0.5.
    call = black_scholes("C", 42, 40, 0.5, 0.2, 0.1)
    put = black_scholes("P", 42, 40, 0.5, 0.2, 0.1)
    assert call.price == pytest.approx(4.76, abs=0.005)
    assert put.price == pytest.approx(0.81, abs=0.005)


def test_greeks_match_hull_reference_values_in_ib_units():
    # Hull delta-hedging example: S=49, K=50, r=5%, sigma=20%, T=20 weeks.
    call = black_scholes("C", 49, 50, 0.3846, 0.2, 0.05)
    assert call.price == pytest.approx(2.40, abs=0.01)
    assert call.delta == pytest.approx(0.522, abs=0.001)
    assert call.gamma == pytest.approx(0.066, abs=0.001)
    assert call.theta == pytest.approx(-4.31 / 365, abs=0.0005)
    assert call.vega == pytest.approx(12.1 / 100, abs=0.001)


@pytest.mark.parametrize("spot,strike,years,vol,rate", [
    (100, 100, 0.25, 0.3, 0.04),
    (50, 70, 1.5, 0.6, 0.02),
    (180, 120, 0.05, 0.9, 0.0),
])
def test_put_call_parity_and_greek_relationships(spot, strike, years, vol, rate):
    call = black_scholes("C", spot, strike, years, vol, rate)
    put = black_scholes("P", spot, strike, years, vol, rate)
    assert call.price - put.price == pytest.approx(
        spot - strike * math.exp(-rate * years), abs=1e-9
    )
    assert call.delta - put.delta == pytest.approx(1.0)
    assert call.gamma == pytest.approx(put.gamma)
    assert call.vega == pytest.approx(put.vega)


@pytest.mark.parametrize("right", ["C", "P"])
def test_greeks_match_finite_differences(right):
    spot, strike, years, vol, rate = 100.0, 95.0, 0.4, 0.35, 0.04
    base = black_scholes(right, spot, strike, years, vol, rate)

    def price(**changes):
        args = {"spot": spot, "years": years, "vol": vol} | changes
        return black_scholes(right, args["spot"], strike, args["years"], args["vol"], rate).price

    h = 0.01
    assert base.delta == pytest.approx((price(spot=spot + h) - price(spot=spot - h)) / (2 * h), abs=1e-6)
    assert base.gamma == pytest.approx(
        (price(spot=spot + h) - 2 * base.price + price(spot=spot - h)) / h**2, abs=1e-4
    )
    one_day = 1 / 365
    assert base.theta == pytest.approx(price(years=years - one_day) - base.price, abs=1e-3)
    assert base.vega == pytest.approx(price(vol=vol + 0.005) - price(vol=vol - 0.005), abs=1e-5)


@pytest.mark.parametrize("right,spot,price,delta", [
    ("C", 110, 10, 1.0), ("C", 90, 0, 0.0), ("C", 100, 0, 0.5),
    ("P", 90, 10, -1.0), ("P", 110, 0, 0.0), ("P", 100, 0, -0.5),
])
def test_expired_options_return_intrinsic_value(right, spot, price, delta):
    for years in (0, -0.01):
        valuation = black_scholes(right, spot, 100, years, 0.3, 0.04)
        assert valuation.price == price
        assert valuation.delta == delta
        assert (valuation.gamma, valuation.theta, valuation.vega) == (0, 0, 0)


def test_zero_volatility_returns_discounted_intrinsic_without_dividing_by_zero():
    years, rate = 0.5, 0.04
    present_strike = 100 * math.exp(-rate * years)
    call = black_scholes("C", 110, 100, years, 0, rate)
    put = black_scholes("P", 90, 100, years, 0, rate)
    otm_call = black_scholes("C", 90, 100, years, 0, rate)
    assert call.price == pytest.approx(110 - present_strike)
    assert (call.delta, call.gamma, call.vega) == (1, 0, 0)
    assert call.theta == pytest.approx(-rate * present_strike / 365)
    assert put.price == pytest.approx(present_strike - 90)
    assert put.delta == -1
    assert put.theta == pytest.approx(rate * present_strike / 365)
    assert (otm_call.price, otm_call.delta, otm_call.theta) == (0, 0, 0)


def test_tiny_time_and_volatility_stay_finite():
    valuation = black_scholes("P", 100, 100, 1e-9, 1e-9, 0.04)
    assert all(math.isfinite(value) for value in vars(valuation).values())


@pytest.mark.parametrize("right,spot,strike", [("X", 100, 100), ("C", 0, 100), ("P", 100, -1)])
def test_invalid_inputs_raise(right, spot, strike):
    with pytest.raises(ValueError):
        black_scholes(right, spot, strike, 0.5, 0.3, 0.04)


@pytest.mark.parametrize("right,spot,strike,years,vol,rate", [
    ("C", 100, 100, 0.25, 0.3, 0.04),
    ("P", 100, 100, 0.25, 0.3, 0.04),
    ("C", 100, 150, 0.1, 1.2, 0.04),
    ("P", 100, 60, 2.0, 0.15, 0.0),
    ("P", 100, 130, 0.5, 0.45, 0.04),
    ("C", 250, 200, 0.02, 0.5, 0.04),
])
def test_solver_recovers_known_volatility(right, spot, strike, years, vol, rate):
    price = black_scholes(right, spot, strike, years, vol, rate).price
    solved = implied_volatility(right, price, spot, strike, years, rate)
    assert solved == pytest.approx(vol, abs=1e-5)


@pytest.mark.parametrize("right,price,spot,strike", [
    ("C", 9.99, 110, 100),
    ("P", 4.5, 95, 100),
])
def test_solver_returns_none_below_intrinsic(right, price, spot, strike):
    assert price < intrinsic_value(right, spot, strike)
    assert implied_volatility(right, price, spot, strike, 0.25, 0.04) is None


def test_solver_returns_minimum_iv_for_deep_itm_calls_under_the_european_bound():
    # S - K*e^(-rT) = 100 - 50*e^(-0.04) ~= 51.96 is above intrinsic (50).
    floor = black_scholes("C", 100, 50, 1.0, MIN_IV, 0.04).price
    for price in (50.0, 51.0, floor):
        assert intrinsic_value("C", 100, 50) <= price <= floor
        assert implied_volatility("C", price, 100, 50, 1.0, 0.04) == MIN_IV
    assert implied_volatility("C", 49.9, 100, 50, 1.0, 0.04) is None


@pytest.mark.parametrize("years", [0, -0.1])
def test_solver_returns_none_for_expired_contracts(years):
    assert implied_volatility("C", 2.0, 100, 100, years, 0.04) is None


@pytest.mark.parametrize("price", [0, -1, 150])
def test_solver_returns_none_for_unsolvable_prices(price):
    # A call can never be worth more than the stock; zero or negative prices have no IV.
    assert implied_volatility("C", price, 100, 100, 0.25, 0.04) is None


def test_risk_free_rate_defaults_to_four_percent():
    assert Settings().risk_free_rate == 0.04
