import pytest

from app.options_screeners.domain import (
    build_cc_candidate,
    build_credit_spread_candidate,
    build_csp_candidate,
    cc_annualized_return,
    cc_gain_percentage,
    credit_spread_annualized_return,
    credit_spread_distance_percentage,
    csp_annualized_return,
    csp_discount_percentage,
    matches_filters,
    midpoint,
    sort_candidates,
    spread_pricing,
)
from app.schemas import (
    CreditSpreadScreenerFilters,
    OptionContractIdentity,
    OptionsScreenerFilters,
)

CONTRACT = OptionContractIdentity(con_id=123, local_symbol="AAPL  260717P00100000")


def test_midpoint_and_single_leg_formulas_use_full_precision():
    mid_credit = midpoint(1.01, 1.04)

    assert mid_credit == pytest.approx(1.025)
    assert csp_annualized_return(mid_credit, 100, 30) == pytest.approx(
        (1.025 / 100) * (365 / 30) * 100
    )
    assert cc_annualized_return(mid_credit, 110, 30) == pytest.approx(
        (1.025 / 110) * (365 / 30) * 100
    )
    assert csp_discount_percentage(110, 100) == pytest.approx((10 / 110) * 100)
    assert cc_gain_percentage(110, 120) == pytest.approx((10 / 110) * 100)


def test_credit_spread_formulas_use_net_market_and_maximum_loss():
    pricing = spread_pricing(
        short_bid=2.10,
        short_ask=2.30,
        long_bid=0.90,
        long_ask=1.00,
    )

    assert pricing is not None
    assert pricing.net_bid == pytest.approx(1.10)
    assert pricing.net_ask == pytest.approx(1.40)
    assert pricing.midpoint == pytest.approx(1.25)
    assert credit_spread_annualized_return(1.25, 5, 30) == pytest.approx(
        (1.25 / 3.75) * (365 / 30) * 100
    )
    assert credit_spread_distance_percentage(
        "put_credit_spread", 110, 100
    ) == pytest.approx((10 / 110) * 100)
    assert credit_spread_distance_percentage(
        "call_credit_spread", 110, 120
    ) == pytest.approx((10 / 110) * 100)


@pytest.mark.parametrize(
    ("net_credit", "width"),
    [(0, 5), (-0.01, 5), (5, 5), (5.01, 5)],
)
def test_credit_spread_return_requires_credit_inside_width(net_credit, width):
    assert credit_spread_annualized_return(net_credit, width, 30) is None


def test_filters_are_inclusive_and_keep_signed_delta_on_candidate():
    filters = OptionsScreenerFilters(
        minimum_dte=7,
        maximum_dte=45,
        minimum_absolute_delta=0.15,
        maximum_absolute_delta=0.30,
        minimum_annualized_return=10,
    )
    candidate = build_csp_candidate(
        ticker="AAPL",
        stock_price=110,
        strike=100,
        expiration="2026-07-17",
        dte=7,
        delta=-0.15,
        bid=1,
        ask=1.10,
        contract=CONTRACT,
    )

    assert candidate is not None
    assert candidate.delta == -0.15
    assert matches_filters(
        dte=candidate.dte,
        delta=candidate.delta,
        annualized_return=10,
        filters=filters,
    )
    assert matches_filters(
        dte=45,
        delta=0.30,
        annualized_return=10,
        filters=filters,
    )
    assert not matches_filters(
        dte=7,
        delta=-0.149,
        annualized_return=10,
        filters=filters,
    )


def test_credit_spread_filters_use_short_leg_absolute_delta():
    filters = CreditSpreadScreenerFilters(
        strategy_types=["put_credit_spread"],
        spread_widths=[5],
    )

    assert matches_filters(
        dte=30,
        delta=-0.30,
        annualized_return=10,
        filters=filters,
    )


def test_candidate_builders_retain_contract_identity_and_raw_values():
    csp = build_csp_candidate(
        ticker="AAPL",
        stock_price=110.1234,
        strike=100,
        expiration="2026-07-17",
        dte=30,
        delta=-0.23456,
        bid=1.01,
        ask=1.04,
        contract=CONTRACT,
    )
    cc = build_cc_candidate(
        ticker="AAPL",
        stock_price=110.1234,
        strike=120,
        expiration="2026-07-17",
        dte=30,
        delta=0.23456,
        bid=1.01,
        ask=1.04,
        contract=CONTRACT,
    )
    spread = build_credit_spread_candidate(
        strategy="put_credit_spread",
        ticker="AAPL",
        stock_price=110.1234,
        short_strike=100,
        long_strike=95,
        expiration="2026-07-17",
        dte=30,
        short_delta=-0.23456,
        short_bid=2.10,
        short_ask=2.30,
        long_bid=0.90,
        long_ask=1.00,
        short_contract=CONTRACT,
        long_contract=OptionContractIdentity(con_id=456, local_symbol="LONG"),
    )

    assert csp is not None
    assert cc is not None
    assert spread is not None
    assert csp.bid == 1.01
    assert csp.delta == -0.23456
    assert csp.contract == CONTRACT
    assert cc.gain_percentage == pytest.approx(
        ((120 - 110.1234) / 110.1234) * 100
    )
    assert spread.short_contract.con_id == 123
    assert spread.long_contract.local_symbol == "LONG"


@pytest.mark.parametrize(
    "missing_field",
    [
        "stock_price",
        "strike",
        "dte",
        "delta",
        "bid",
        "ask",
    ],
)
def test_missing_single_leg_fields_exclude_candidate(missing_field):
    values = {
        "stock_price": 110,
        "strike": 100,
        "dte": 30,
        "delta": -0.20,
        "bid": 1,
        "ask": 1.10,
    }
    values[missing_field] = None

    candidate = build_csp_candidate(
        ticker="AAPL",
        expiration="2026-07-17",
        contract=CONTRACT,
        **values,
    )

    assert candidate is None


@pytest.mark.parametrize(
    "missing_field",
    [
        "stock_price",
        "short_strike",
        "long_strike",
        "dte",
        "short_delta",
        "short_bid",
        "short_ask",
        "long_bid",
        "long_ask",
    ],
)
def test_missing_credit_spread_fields_exclude_candidate(missing_field):
    values = {
        "stock_price": 110,
        "short_strike": 100,
        "long_strike": 95,
        "dte": 30,
        "short_delta": -0.20,
        "short_bid": 2.10,
        "short_ask": 2.30,
        "long_bid": 0.90,
        "long_ask": 1.00,
    }
    values[missing_field] = None

    candidate = build_credit_spread_candidate(
        strategy="put_credit_spread",
        ticker="AAPL",
        expiration="2026-07-17",
        short_contract=CONTRACT,
        long_contract=CONTRACT,
        **values,
    )

    assert candidate is None


def test_default_sorting_uses_full_precision_and_deterministic_ties():
    candidates = [
        csp_candidate("later", annualized_return=10.001, dte=30, ticker="MSFT"),
        csp_candidate("first", annualized_return=10.004, dte=30, ticker="AAPL"),
        csp_candidate("second", annualized_return=10.004, dte=30, ticker="AAPL"),
        csp_candidate("shorter", annualized_return=10.004, dte=20, ticker="MSFT"),
        csp_candidate(
            "strike",
            annualized_return=10.004,
            dte=30,
            ticker="AAPL",
            strike=105,
        ),
    ]

    sorted_candidates = sort_candidates(candidates)

    assert [candidate.contract.local_symbol for candidate in sorted_candidates] == [
        "shorter",
        "first",
        "second",
        "strike",
        "later",
    ]


def csp_candidate(
    identity: str,
    *,
    annualized_return: float,
    dte: int,
    ticker: str,
    strike: float = 100,
):
    candidate = build_csp_candidate(
        ticker=ticker,
        stock_price=110,
        strike=strike,
        expiration="2026-07-17",
        dte=dte,
        delta=-0.20,
        bid=1,
        ask=1.10,
        contract=OptionContractIdentity(local_symbol=identity),
    )
    assert candidate is not None
    return candidate.model_copy(update={"annualized_return": annualized_return})
