from datetime import UTC, datetime

import pytest

from app.ib.portfolio import AnalysisMarketData
from app.portfolio_analysis.beta import ResolvedBeta
from app.portfolio_analysis.exposure import build_account_exposure, years_to_expiry
from app.portfolio_analysis.pricing import black_scholes
from app.schemas import PortfolioAccountSummary, PortfolioPosition

NOW = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
NEAR = "20261016"
FAR = "20270115"
RATE = 0.04
SPOT = 100.0
FX_SGD = 0.75

_next_con_id = iter(range(1, 1_000))


def opt(symbol, right, strike, quantity, average_cost=100.0, *, expiry=NEAR, account="U1"):
    return PortfolioPosition(
        account=account,
        con_id=next(_next_con_id),
        symbol=symbol,
        sec_type="OPT",
        expiry=expiry,
        strike=strike,
        right=right,
        multiplier="100",
        exchange="SMART",
        currency="USD",
        quantity=quantity,
        average_cost=average_cost,
    )


def stock(symbol, quantity, average_cost, *, currency="USD", sec_type="STK", account="U1"):
    return PortfolioPosition(
        account=account,
        con_id=next(_next_con_id),
        symbol=symbol,
        sec_type=sec_type,
        exchange="SMART",
        currency=currency,
        quantity=quantity,
        average_cost=average_cost,
    )


def ib_greeks(position, spot=SPOT):
    call_delta = min(0.95, max(0.05, 0.5 - (position.strike - spot) / 50))
    return {
        "delta": call_delta if position.right == "C" else call_delta - 1,
        "gamma": 0.02,
        "theta": -0.04,
        "vega": 0.1,
        "implied_volatility": 0.4,
        "underlying_price": spot,
    }


def fixture_portfolio():
    aapl = stock("AAPL", 200, 150.0)
    positions = [
        aapl,
        opt("AAPL", "C", 210, -1, 300),  # covered call with 100 spare shares
        opt("AMD", "P", 95, -1, 250), opt("AMD", "P", 90, 1, 100),  # put credit spread
        opt("AMZN", "C", 105, -1, 250), opt("AMZN", "C", 110, 1, 100),  # call credit
        opt("META", "P", 105, 1, 600), opt("META", "P", 100, -1, 300),  # put debit
        opt("MSFT", "C", 95, 1, 600), opt("MSFT", "C", 100, -1, 300),  # call debit
        opt("NVDA", "C", 80, 1, 2_200, expiry=FAR), opt("NVDA", "C", 110, -1, 100),  # PMCC
        opt("TSLA", "P", 120, 1, 2_100, expiry=FAR), opt("TSLA", "P", 90, -1, 100),  # PMCP
        opt("GOOG", "C", 100, 2, 800, expiry=FAR),  # long call
        opt("NFLX", "P", 100, 1, 700),  # long put
        opt("UBER", "C", 120, -1, 150),  # naked call
        opt("HIMS", "P", 25, -2, 80),  # short put, fallback Greeks and fallback beta
        stock("D05", 100, 35.0, currency="SGD"),  # converted at IB's ledger rate
        stock("ES", 1, 5_000.0, sec_type="FUT"),  # unsupported
        stock("AAPL", 50, 100.0, account="U2"),  # other account
    ]
    hims = positions[-4]
    by_con_id = {
        position.con_id: ib_greeks(position)
        for position in positions
        if position.sec_type == "OPT" and position.symbol not in ("AAPL", "HIMS")
    }
    by_con_id[positions[1].con_id] = ib_greeks(positions[1], spot=200)
    by_con_id[aapl.con_id] = {"last": 200.0}
    # HIMS has IB's IV but no Greeks, so they come from Black-Scholes.
    by_con_id[hims.con_id] = {"implied_volatility": 0.6, "last": 0.9}
    by_con_id[positions[-3].con_id] = {"last": 40.0}
    market = AnalysisMarketData(
        by_con_id=by_con_id,
        underlyings={
            symbol: {"last": SPOT}
            for symbol in ("AMD", "AMZN", "META", "MSFT", "NVDA", "TSLA", "GOOG", "NFLX", "UBER")
        } | {"HIMS": {"last": 28.0}},
        exchange_rates={"U1": {"SGD": FX_SGD}},
    )
    betas = {
        symbol: ResolvedBeta(symbol, 1.5, "computed", 252)
        for symbol in ("AMD", "AMZN", "META", "MSFT", "NVDA", "TSLA", "GOOG", "NFLX", "UBER", "D05")
    } | {"AAPL": ResolvedBeta("AAPL", 1.2, "override")}
    summary = PortfolioAccountSummary(
        account="U1",
        net_liquidation=100_000,
        maintenance_margin=20_000,
        excess_liquidity=80_000,
    )
    return positions, market, betas, summary


def build(positions, market, betas, summary):
    return build_account_exposure(
        "U1", positions, summary, market, betas, now=NOW, risk_free_rate=RATE,
    )


def hims_model():
    return black_scholes("P", 28.0, 25, years_to_expiry(NEAR, NOW), 0.6, RATE)


def expected_position_exposure(position, market, betas):
    """Independent per-position sum, before any strategy pairing."""
    beta = betas[position.symbol].beta if position.symbol in betas else 1.0
    if position.sec_type == "STK":
        price = market.by_con_id[position.con_id]["last"]
        fx = FX_SGD if position.currency == "SGD" else 1.0
        dollar_delta = position.quantity * price * fx
        return dollar_delta, dollar_delta * beta, 0.0, 0.0, 0.0
    if position.symbol == "HIMS":
        model = hims_model()
        spot = 28.0
        greeks = (model.delta, model.gamma, model.theta, model.vega)
    else:
        values = market.by_con_id[position.con_id]
        spot = values["underlying_price"]
        greeks = (values["delta"], values["gamma"], values["theta"], values["vega"])
    delta, gamma, theta, vega = greeks
    scale = 100 * position.quantity
    dollar_delta = delta * scale * spot
    return dollar_delta, dollar_delta * beta, gamma * scale * spot**2 / 100, theta * scale, vega * scale


def test_fixture_portfolio_aggregates_match_position_sums():
    positions, market, betas, summary = fixture_portfolio()
    result = build(positions, market, betas, summary)

    supported = [
        position for position in positions if position.account == "U1" and position.sec_type != "FUT"
    ]
    totals = [sum(values) for values in zip(*(
        expected_position_exposure(position, market, betas) for position in supported
    ))]
    s = result.summary
    assert [s.net_dollar_delta, s.beta_weighted_delta, s.net_gamma, s.net_theta, s.net_vega] == (
        pytest.approx(totals)
    )
    assert s.gross_dollar_delta == pytest.approx(
        sum(abs(underlying.dollar_delta) for underlying in result.underlyings)
    )
    assert s.gross_dollar_delta > abs(s.net_dollar_delta)
    assert s.beta_weighted_delta_multiple == pytest.approx(s.beta_weighted_delta / 100_000)
    assert s.net_liquidation == 100_000
    assert s.maintenance_margin == 20_000
    assert s.margin_utilisation_percent == pytest.approx(20)
    assert s.excess_liquidity == 80_000

    # Naked put strike x 100 x 2, plus the AMD put credit spread's width minus credit.
    assert s.assignment_exposure == pytest.approx(25 * 100 * 2 + (500 - 150))
    assert s.assignment_exposure_percent == pytest.approx(5.35)

    # AAPL is the largest: 200 shares at $200 less the short call's delta.
    aapl = next(underlying for underlying in result.underlyings if underlying.symbol == "AAPL")
    assert aapl.dollar_delta == pytest.approx(200 * 200 - 0.3 * 100 * 200)
    assert s.largest_underlying == "AAPL"
    assert s.largest_underlying_percent == pytest.approx(34)

    assert s.coverage.model_dump() == {
        "positions": 20,
        "fallback_greeks": 1,
        "fallback_beta": 1,
        "unsupported": 1,
        "fx_converted": 1,
        "missing_price": 0,
    }


def test_every_group_type_is_reported_under_its_underlying():
    positions, market, betas, summary = fixture_portfolio()
    result = build(positions, market, betas, summary)

    kinds = {
        underlying.symbol: [group.kind for group in underlying.groups]
        for underlying in result.underlyings
    }
    assert kinds == {
        "AAPL": ["covered_call", "stock"],
        "AMD": ["put_credit_spread"],
        "AMZN": ["call_credit_spread"],
        "META": ["put_debit_spread"],
        "MSFT": ["call_debit_spread"],
        "NVDA": ["pmcc"],
        "TSLA": ["pmcp"],
        "GOOG": ["long_call"],
        "NFLX": ["long_put"],
        "UBER": ["naked_call"],
        "HIMS": ["short_put"],
        "D05": ["stock"],
    }
    # Underlyings are ordered by absolute beta-weighted delta.
    weights = [abs(underlying.beta_weighted_delta) for underlying in result.underlyings]
    assert weights == sorted(weights, reverse=True)

    aapl = result.underlyings[0]
    assert (aapl.beta, aapl.beta_source) == (1.2, "override")
    assert aapl.underlying_price == 200
    covered_call, spare_stock = aapl.groups
    assert [leg.quantity for leg in covered_call.legs] == [100, -1]
    assert covered_call.dollar_delta == pytest.approx(100 * 200 - 0.3 * 100 * 200)
    assert covered_call.beta_weighted_delta == pytest.approx(covered_call.dollar_delta * 1.2)
    assert covered_call.theta == pytest.approx(0.04 * 100)
    assert covered_call.max_loss == pytest.approx(15_000 - 300)
    assert spare_stock.dollar_delta == pytest.approx(20_000)
    assert aapl.max_loss == pytest.approx(15_000 - 300 + 15_000)
    assert aapl.max_loss_unlimited is False

    uber = next(underlying for underlying in result.underlyings if underlying.symbol == "UBER")
    assert (uber.max_loss, uber.max_loss_unlimited) == (None, True)

    for underlying in result.underlyings:
        for group in underlying.groups:
            assert group.dollar_delta == pytest.approx(sum(leg.dollar_delta for leg in group.legs))
        assert underlying.dollar_delta == pytest.approx(
            sum(group.dollar_delta for group in underlying.groups)
        )


def test_fallback_greeks_and_fallback_beta_are_flagged():
    positions, market, betas, summary = fixture_portfolio()
    result = build(positions, market, betas, summary)

    hims = next(underlying for underlying in result.underlyings if underlying.symbol == "HIMS")
    assert (hims.beta, hims.beta_source) == (1.0, "fallback")
    leg = hims.groups[0].legs[0]
    model = hims_model()
    assert leg.greeks_source == "fallback"
    assert leg.implied_volatility == 0.6
    assert leg.delta == pytest.approx(model.delta)
    assert leg.dollar_delta == pytest.approx(model.delta * 100 * -2 * 28)
    assert leg.theta == pytest.approx(model.theta * 100 * -2)
    assert leg.flags == ["fallback_beta", "fallback_greeks"]
    assert hims.assignment_exposure == 5_000
    assert hims.net_liquidation_percent == pytest.approx(abs(leg.dollar_delta) / 1_000)

    amd = next(underlying for underlying in result.underlyings if underlying.symbol == "AMD")
    amd_leg = amd.groups[0].legs[0]
    assert amd_leg.greeks_source == "ib"
    assert amd_leg.flags == []


def test_non_usd_positions_convert_at_the_ledger_rate():
    positions, market, betas, summary = fixture_portfolio()
    result = build(positions, market, betas, summary)

    dbs = next(underlying for underlying in result.underlyings if underlying.symbol == "D05")
    leg = dbs.groups[0].legs[0]
    assert leg.fx_rate == FX_SGD
    assert leg.dollar_delta == pytest.approx(100 * 40 * FX_SGD)
    assert leg.flags == ["fx_converted"]
    assert dbs.groups[0].max_loss == pytest.approx(3_500 * FX_SGD)

    no_rate = AnalysisMarketData(market.by_con_id, market.underlyings, exchange_rates={})
    result = build(positions, no_rate, betas, summary)
    assert [(item.symbol, item.reason) for item in result.unsupported] == [
        ("D05", "No IB exchange rate for SGD."),
        ("ES", "Unsupported instrument (FUT)."),
    ]


def test_unsupported_and_other_account_positions_are_excluded():
    positions, market, betas, summary = fixture_portfolio()
    result = build(positions, market, betas, summary)

    assert [item.model_dump() for item in result.unsupported] == [{
        "con_id": positions[-2].con_id,
        "symbol": "ES",
        "sec_type": "FUT",
        "local_symbol": None,
        "currency": "USD",
        "quantity": 1,
        "reason": "Unsupported instrument (FUT).",
    }]
    aapl = result.underlyings[0]
    assert sum(group.quantity for group in aapl.groups if group.kind == "stock") == 100


def test_missing_iv_is_solved_from_the_option_price():
    position = opt("HIMS", "P", 25, -1)
    market = AnalysisMarketData(
        by_con_id={position.con_id: {"last": 0.9}},
        underlyings={"HIMS": {"last": 28.0}},
    )
    result = build([position], market, {}, None)
    leg = result.underlyings[0].groups[0].legs[0]

    model = black_scholes("P", 28.0, 25, years_to_expiry(NEAR, NOW), leg.implied_volatility, RATE)
    assert leg.greeks_source == "solved_iv"
    assert model.price == pytest.approx(0.9, abs=1e-6)
    assert leg.delta == pytest.approx(model.delta)
    assert "solved_iv" in leg.flags
    assert result.summary.net_liquidation is None
    assert result.summary.beta_weighted_delta_multiple is None
    assert result.summary.coverage.fallback_greeks == 1


def test_deep_itm_call_under_the_european_bound_keeps_its_delta():
    # A PMCC-style long call quoted at intrinsic while IB sends no Greeks.
    position = opt("HIMS", "C", 10, 1, expiry=FAR)
    market = AnalysisMarketData(
        by_con_id={position.con_id: {"close": 18.0}},
        underlyings={"HIMS": {"last": 28.0}},
    )
    leg = build([position], market, {}, None).underlyings[0].groups[0].legs[0]

    assert leg.greeks_source == "solved_iv"
    assert "missing_greeks" not in leg.flags
    assert leg.delta == pytest.approx(1.0)
    assert leg.dollar_delta == pytest.approx(100 * 28.0)


def test_partial_ib_greeks_are_kept_and_the_rest_filled():
    position = opt("HIMS", "C", 30, 1)
    market = AnalysisMarketData(
        by_con_id={position.con_id: {"delta": 0.42, "implied_volatility": 0.5}},
        underlyings={"HIMS": {"last": 28.0}},
    )
    leg = build([position], market, {}, None).underlyings[0].groups[0].legs[0]
    model = black_scholes("C", 28.0, 30, years_to_expiry(NEAR, NOW), 0.5, RATE)

    assert leg.greeks_source == "fallback"
    assert leg.delta == 0.42
    assert leg.vega == pytest.approx(model.vega * 100)


def test_positions_without_prices_are_counted_not_guessed():
    position = opt("HIMS", "C", 30, 1)
    held = stock("SOFI", 10, 8.0)
    result = build([position, held], AnalysisMarketData({}, {}), {}, None)

    assert result.summary.net_dollar_delta == 0
    assert result.summary.coverage.missing_price == 2
    assert result.summary.coverage.fallback_greeks == 1
    leg = result.underlyings[0].groups[0].legs[0]
    assert leg.greeks_source == "missing"


def test_years_to_expiry_uses_the_new_york_close():
    assert years_to_expiry("20260928", NOW) == pytest.approx(6 / (365 * 24))
    assert years_to_expiry("20260925", NOW) < 0
    assert years_to_expiry("bad", NOW) == 0


def test_ib_mark_solves_iv_when_no_quote_arrives():
    # IB's P&L value for -2 contracts is negative; the mark is per share.
    short_put = opt("HIMS", "P", 25, -2).model_copy(update={"market_value": -180.0})
    market = AnalysisMarketData(by_con_id={}, underlyings={"HIMS": {"last": 28.0}})
    leg = build([short_put], market, {}, None).underlyings[0].groups[0].legs[0]

    model = black_scholes("P", 28.0, 25, years_to_expiry(NEAR, NOW), leg.implied_volatility, RATE)
    assert leg.greeks_source == "solved_iv"
    assert leg.price == pytest.approx(0.9)
    assert model.price == pytest.approx(0.9, abs=1e-6)
    assert leg.flags == ["fallback_beta", "solved_iv", "mark_price"]
    assert leg.dollar_delta == pytest.approx(model.delta * 100 * -2 * 28)


def test_quotes_take_priority_over_the_ib_mark():
    position = opt("HIMS", "P", 25, -1).model_copy(update={"market_value": -500.0})
    market = AnalysisMarketData(
        by_con_id={position.con_id: {"close": 0.9}},
        underlyings={"HIMS": {"last": 28.0}},
    )
    leg = build([position], market, {}, None).underlyings[0].groups[0].legs[0]
    assert leg.price == 0.9
    assert "mark_price" not in leg.flags

    with_greeks = AnalysisMarketData(
        by_con_id={position.con_id: ib_greeks(position, spot=28.0) | {"implied_volatility": 0.5}},
        underlyings={"HIMS": {"last": 28.0}},
    )
    leg = build([position], with_greeks, {}, None).underlyings[0].groups[0].legs[0]
    assert leg.greeks_source == "ib"
    assert leg.flags == ["fallback_beta"]


@pytest.mark.parametrize("market_value", [None, 0.0, 180.0])
def test_unusable_marks_leave_greeks_missing(market_value):
    # A positive value on a short position is not a valid mark.
    position = opt("HIMS", "P", 25, -2).model_copy(update={"market_value": market_value})
    market = AnalysisMarketData(by_con_id={}, underlyings={"HIMS": {"last": 28.0}})
    leg = build([position], market, {}, None).underlyings[0].groups[0].legs[0]
    assert leg.greeks_source == "missing"
    assert leg.dollar_delta == 0
