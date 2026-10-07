import pytest

from app.portfolio_analysis.pairing import (
    is_supported_position,
    pair_strategies,
)
from app.schemas import PortfolioPosition

NEAR = "20261016"
FAR = "20270115"


def opt(
    right: str,
    strike: float,
    quantity: float,
    average_cost: float,
    *,
    expiry: str = NEAR,
    symbol: str = "HIMS",
    account: str = "U1",
    multiplier: str = "100",
) -> PortfolioPosition:
    return PortfolioPosition(
        account=account,
        con_id=hash((symbol, right, strike, expiry)) % 1_000_000,
        symbol=symbol,
        sec_type="OPT",
        expiry=expiry,
        strike=strike,
        right=right,
        multiplier=multiplier,
        exchange="SMART",
        currency="USD",
        quantity=quantity,
        average_cost=average_cost,
    )


def stock(quantity: float, average_cost: float = 30.0, symbol: str = "HIMS", account: str = "U1"):
    return PortfolioPosition(
        account=account,
        con_id=1,
        symbol=symbol,
        sec_type="STK",
        exchange="NASDAQ",
        currency="USD",
        quantity=quantity,
        average_cost=average_cost,
    )


def summary(groups):
    return [
        (
            group.kind,
            group.quantity,
            tuple((leg.position.right or "S", leg.position.strike, leg.quantity) for leg in group.legs),
        )
        for group in groups
    ]


def only(groups, kind):
    matches = [group for group in groups if group.kind == kind]
    assert len(matches) == 1, summary(groups)
    return matches[0]


@pytest.mark.parametrize(
    "short, long, kind, premium_type, net_premium, max_loss, exposure",
    [
        # Short higher put, long lower put: credit 1.50 - 0.50 on a 5-wide spread.
        (("P", 100, 150), ("P", 95, 50), "put_credit_spread", "credit", 100, 400, 400),
        # Short lower call, long higher call.
        (("C", 100, 150), ("C", 105, 50), "call_credit_spread", "credit", 100, 400, 0),
        # Long higher put, short lower put: pay 3.00, receive 1.00.
        (("P", 95, 100), ("P", 100, 300), "put_debit_spread", "debit", -200, 200, 0),
        # Long lower call, short higher call.
        (("C", 105, 100), ("C", 100, 300), "call_debit_spread", "debit", -200, 200, 0),
    ],
)
def test_vertical_types_are_classified_by_structure(
    short, long, kind, premium_type, net_premium, max_loss, exposure,
):
    groups = pair_strategies([
        opt(short[0], short[1], -1, short[2]),
        opt(long[0], long[1], 1, long[2]),
    ])
    group = only(groups, kind)
    assert len(groups) == 1
    assert group.premium_type == premium_type
    assert group.net_premium == pytest.approx(net_premium)
    assert group.max_loss == pytest.approx(max_loss)
    assert group.assignment_exposure == pytest.approx(exposure)
    assert [leg.quantity for leg in group.legs] == [-1, 1]


def test_single_leg_and_stock_groups():
    groups = pair_strategies([
        opt("P", 25, -2, 80),
        opt("C", 40, -1, 60),
        opt("C", 30, 3, 200, symbol="AMD"),
        opt("P", 20, 1, 90, symbol="AMD"),
        stock(40, 25.0),
        stock(-10, 50.0, symbol="SOFI"),
    ])

    short_put = only(groups, "short_put")
    assert (short_put.quantity, short_put.premium_type) == (2, "credit")
    assert short_put.net_premium == 160
    assert short_put.assignment_exposure == 25 * 100 * 2
    assert short_put.max_loss == 5_000 - 160

    naked_call = only(groups, "naked_call")
    assert naked_call.max_loss is None
    assert naked_call.assignment_exposure == 0

    long_call = only(groups, "long_call")
    assert (long_call.quantity, long_call.premium_type, long_call.max_loss) == (3, "debit", 600)
    long_put = only(groups, "long_put")
    assert (long_put.net_premium, long_put.max_loss) == (-90, 90)

    stocks = [group for group in groups if group.kind == "stock"]
    assert [(group.symbol, group.quantity, group.max_loss) for group in stocks] == [
        ("HIMS", 40, 1_000),
        ("SOFI", 10, None),
    ]


def test_covered_call_uses_held_shares():
    groups = pair_strategies([stock(200, 30.0), opt("C", 35, -2, 120)])
    covered = only(groups, "covered_call")
    assert len(groups) == 1
    assert covered.quantity == 2
    assert [leg.quantity for leg in covered.legs] == [200, -2]
    assert covered.premium_type == "credit"
    assert covered.net_premium == 240
    assert covered.max_loss == 6_000 - 240
    assert covered.assignment_exposure == 0


def test_stock_too_small_to_cover_a_call():
    groups = pair_strategies([stock(50), opt("C", 35, -1, 100)])
    assert summary(groups) == [
        ("naked_call", 1, (("C", 35, -1),)),
        ("stock", 50, (("S", None, 50),)),
    ]


def test_partial_cover_splits_calls_and_leaves_spare_shares():
    groups = pair_strategies([stock(250), opt("C", 35, -3, 100)])
    assert summary(groups) == [
        ("covered_call", 2, (("S", None, 200), ("C", 35, -2))),
        ("naked_call", 1, (("C", 35, -1),)),
        ("stock", 50, (("S", None, 50),)),
    ]


def test_covered_call_takes_priority_over_pmcc():
    groups = pair_strategies([
        stock(100),
        opt("C", 35, -1, 100),
        opt("C", 20, 1, 1_200, expiry=FAR),
    ])
    assert [group.kind for group in groups] == ["covered_call", "long_call"]


def test_pmcc_and_put_mirror_image():
    groups = pair_strategies([
        opt("C", 35, -1, 100),
        opt("C", 20, 1, 1_200, expiry=FAR),
        opt("P", 25, -1, 90),
        opt("P", 40, 1, 1_100, expiry=FAR),
    ])
    pmcc = only(groups, "pmcc")
    assert [(leg.position.strike, leg.quantity) for leg in pmcc.legs] == [(20, 1), (35, -1)]
    assert pmcc.premium_type == "debit"
    assert pmcc.net_premium == -1_100
    assert pmcc.max_loss == 1_100
    pmcp = only(groups, "pmcp")
    assert [(leg.position.strike, leg.quantity) for leg in pmcp.legs] == [(40, 1), (25, -1)]
    assert pmcp.max_loss == 1_010
    assert pmcp.assignment_exposure == 0
    assert len(groups) == 2


def test_calendars_pair_and_diagonals_need_same_or_better_strike():
    groups = pair_strategies([
        # Call calendar: same strike, later expiry.
        opt("C", 30, -1, 100),
        opt("C", 30, 1, 300, expiry=FAR),
        # Put calendar.
        opt("P", 28, -1, 100),
        opt("P", 28, 1, 300, expiry=FAR),
        # Call diagonal with a worse long strike stays naked.
        opt("C", 40, -1, 50, symbol="AMD"),
        opt("C", 45, 1, 150, symbol="AMD", expiry=FAR),
        # Put diagonal with a worse long strike stays naked.
        opt("P", 20, -1, 50, symbol="SOFI"),
        opt("P", 15, 1, 150, symbol="SOFI", expiry=FAR),
        # A long that expires before the short cannot cover it.
        opt("C", 10, -1, 50, symbol="PLTR", expiry=FAR),
        opt("C", 5, 1, 150, symbol="PLTR"),
    ])
    by_symbol = {}
    for group in groups:
        by_symbol.setdefault(group.symbol, []).append(group.kind)
    assert by_symbol == {
        "HIMS": ["pmcc", "pmcp"],
        "AMD": ["naked_call", "long_call"],
        "SOFI": ["short_put", "long_put"],
        "PLTR": ["naked_call", "long_call"],
    }


def test_several_spreads_on_one_underlying_and_expiry_pair_nearest_strikes():
    groups = pair_strategies([
        opt("P", 100, -1, 300),
        opt("P", 95, 1, 150),
        opt("P", 90, -1, 100),
        opt("P", 85, 1, 40),
        opt("C", 110, -2, 120),
        opt("C", 115, 2, 50),
    ])
    assert summary(groups) == [
        ("put_credit_spread", 1, (("P", 90, -1), ("P", 85, 1))),
        ("put_credit_spread", 1, (("P", 100, -1), ("P", 95, 1))),
        ("call_credit_spread", 2, (("C", 110, -2), ("C", 115, 2))),
    ]


def test_verticals_take_priority_over_covered_calls_and_diagonals():
    groups = pair_strategies([
        stock(100),
        opt("C", 35, -1, 100),
        opt("C", 40, 1, 30),
        opt("C", 20, 1, 1_200, expiry=FAR),
    ])
    assert [group.kind for group in groups] == ["call_credit_spread", "long_call", "stock"]


def test_unequal_quantities_split_into_spreads_and_naked_legs():
    groups = pair_strategies([opt("P", 30, -3, 200), opt("P", 25, 2, 50)])
    assert summary(groups) == [
        ("put_credit_spread", 2, (("P", 30, -2), ("P", 25, 2))),
        ("short_put", 1, (("P", 30, -1),)),
    ]
    spread, naked = groups
    assert spread.net_premium == 300
    assert spread.assignment_exposure == 2 * 5 * 100 - 300
    assert naked.net_premium == 200
    assert naked.assignment_exposure == 3_000

    extra_longs = pair_strategies([opt("C", 30, -1, 200), opt("C", 35, 3, 50)])
    assert summary(extra_longs) == [
        ("call_credit_spread", 1, (("C", 30, -1), ("C", 35, 1))),
        ("long_call", 2, (("C", 35, 2),)),
    ]


def test_accounts_are_paired_separately():
    groups = pair_strategies([
        opt("P", 30, -1, 200, account="U1"),
        opt("P", 25, 1, 50, account="U2"),
    ])
    assert [(group.account, group.kind) for group in groups] == [
        ("U1", "short_put"),
        ("U2", "long_put"),
    ]


def test_unsupported_instruments_are_not_paired():
    future = stock(1).model_copy(update={"sec_type": "FUT", "symbol": "ES"})
    adjusted = opt("P", 30, -1, 200, multiplier="150")
    assert not is_supported_position(future)
    assert not is_supported_position(adjusted)
    assert is_supported_position(opt("P", 30, -1, 200))
    assert pair_strategies([future, adjusted]) == []


def test_missing_average_cost_counts_as_zero_premium():
    groups = pair_strategies([opt("P", 30, -1, 200).model_copy(update={"average_cost": None})])
    assert groups[0].net_premium == 0
    assert groups[0].premium_type == "credit"
    assert groups[0].max_loss == 3_000
