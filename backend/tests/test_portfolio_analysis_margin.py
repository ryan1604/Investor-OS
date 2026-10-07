import pytest
from test_portfolio_analysis_exposure import NOW, RATE, build, fixture_portfolio, opt, stock

from app.ib.portfolio import AnalysisMarketData
from app.portfolio_analysis.beta import ResolvedBeta
from app.portfolio_analysis.margin import (
    MarginLeg,
    calibration_factor,
    distance_to_margin_call,
    group_margin,
    naked_call_margin,
    naked_put_margin,
)
from app.portfolio_analysis.stress import REALISTIC_PATH, build_stress_grid
from app.schemas import PortfolioAccountSummary


def put(quantity, strike, price=1.0):
    return MarginLeg("P", quantity, price, strike)


def call(quantity, strike, price=1.0):
    return MarginLeg("C", quantity, price, strike)


def shares(quantity, price=100.0):
    return MarginLeg(None, quantity, price)


@pytest.mark.parametrize(
    ("kind", "legs", "expected"),
    [
        ("stock", [shares(200)], 0.25 * 200 * 100),
        ("stock", [shares(-100)], 0.30 * 100 * 100),
        ("long_call", [call(2, 100)], 0.0),
        ("long_put", [put(1, 100)], 0.0),
        ("put_debit_spread", [put(1, 105), put(-1, 100)], 0.0),
        ("call_debit_spread", [call(1, 95), call(-1, 100)], 0.0),
        ("put_credit_spread", [put(-2, 95), put(2, 90)], 5 * 100 * 2),
        ("call_credit_spread", [call(-1, 105), call(1, 115)], 10 * 100),
        ("covered_call", [shares(100), call(-1, 110)], 0.25 * 100 * 100),
        ("pmcc", [call(1, 80), call(-1, 110)], 0.0),
        ("pmcp", [put(1, 120), put(-1, 90)], 0.0),
        ("pmcp", [put(1, 95), put(-1, 100)], 5 * 100),
        # 20% x 100 - 5 OTM = 15 beats 10% x 95 = 9.5; plus 1.0 premium.
        ("short_put", [put(-2, 95)], (15 + 1) * 100 * 2),
        # 20% x 100 - 5 OTM = 15 beats 10% x 100 = 10; plus 0.5 premium.
        ("naked_call", [call(-1, 105, 0.5)], (15 + 0.5) * 100),
    ],
)
def test_group_rules(kind, legs, expected):
    assert group_margin(kind, legs, 100.0) == pytest.approx(expected)


def test_naked_minimum_floors():
    # Far OTM put: 20% x 100 - 40 is negative, so 10% of the strike applies.
    assert naked_put_margin(100.0, 60.0, 0.05) == pytest.approx(6.0 + 0.05)
    # Far OTM call: 10% of the underlying applies.
    assert naked_call_margin(100.0, 150.0, 0.05) == pytest.approx(10.0 + 0.05)
    # ITM: no OTM reduction.
    assert naked_put_margin(80.0, 100.0, 21.0) == pytest.approx(16.0 + 21.0)
    assert naked_call_margin(120.0, 100.0, 21.0) == pytest.approx(24.0 + 21.0)


@pytest.mark.parametrize(
    ("ib_margin", "model_margin", "expected"),
    [(None, 10_000, 1.0), (8_000, 10_000, 1.0), (15_000, 10_000, 1.5), (5_000, 0, 1.0)],
)
def test_calibration_factor_is_at_least_one(ib_margin, model_margin, expected):
    assert calibration_factor(ib_margin, model_margin) == pytest.approx(expected)


def fixture_grid(ib_margin):
    positions, market, betas, summary = fixture_portfolio()
    exposure = build(positions, market, betas, summary)
    return build_stress_grid(exposure.underlyings, 100_000, ib_margin, now=NOW, risk_free_rate=RATE)


@pytest.mark.parametrize("scale", [0.5, 1.0, 3.0])
def test_calibration_factor_is_applied_to_every_cell(scale):
    model_margin = fixture_grid(None).margin.model_margin
    assert model_margin > 0

    grid = fixture_grid(model_margin * scale)
    margin = grid.margin
    factor = max(1.0, scale)
    assert margin.model_margin == pytest.approx(model_margin)
    assert margin.calibration_factor == pytest.approx(factor)
    zero = next(
        cell for cell in grid.cells if cell.spy_move_percent == 0 and cell.iv_shock_percent == 0
    )
    assert zero.excess_liquidity == pytest.approx(100_000 - factor * model_margin)

    uncalibrated = fixture_grid(None)
    for cell, base in zip(grid.cells, uncalibrated.cells, strict=True):
        base_margin = 100_000 + base.pnl - base.excess_liquidity
        assert cell.excess_liquidity == pytest.approx(100_000 + cell.pnl - factor * base_margin)


def test_distance_bisects_the_path_segment_that_crosses_zero():
    # Excess liquidity reaches zero at a 12% SPY drop, inside the -10% to -20% segment.
    distance = distance_to_margin_call(lambda move, _: 12_000 + 100_000 * move, REALISTIC_PATH)
    assert distance == pytest.approx(0.12, abs=1e-6)

    assert distance_to_margin_call(lambda move, _: -1.0, REALISTIC_PATH) == 0.0
    assert distance_to_margin_call(lambda move, _: 50_000 + 100_000 * move, REALISTIC_PATH) is None


def test_distance_moves_both_shocks_together():
    seen = []

    def excess_liquidity(move, shock):
        seen.append((move, shock))
        return 1.0 - shock  # zero once the IV shock reaches 100%

    assert distance_to_margin_call(excess_liquidity, REALISTIC_PATH) == pytest.approx(0.30)
    for move, shock in seen:
        if -0.30 <= move <= -0.20:
            expected = 0.80 + (move + 0.20) / -0.10 * 0.20
            assert shock == pytest.approx(expected)


def leveraged_grid(contracts):
    """Short puts on a beta-1 underlying against a $100,000 account."""
    positions = [opt("XYZ", "P", 95, -contracts, 150)]
    market = AnalysisMarketData(
        by_con_id={positions[0].con_id: {"implied_volatility": 0.3}},
        underlyings={"XYZ": {"last": 100.0}},
    )
    betas = {"XYZ": ResolvedBeta("XYZ", 1.0, "computed", 252)}
    summary = PortfolioAccountSummary(account="U1", net_liquidation=100_000)
    exposure = build(positions, market, betas, summary)
    return build_stress_grid(exposure.underlyings, 100_000, None, now=NOW, risk_free_rate=RATE)


def test_distance_to_margin_call_shrinks_as_leverage_rises():
    light = leveraged_grid(5).margin
    assert light.margin_call_beyond_path is True
    assert light.distance_to_margin_call_percent is None

    distances = [
        leveraged_grid(contracts).margin.distance_to_margin_call_percent
        for contracts in (20, 30, 45, 60)
    ]
    assert all(distance is not None for distance in distances)
    assert distances == sorted(distances, reverse=True)
    assert len(set(distances)) == len(distances)
    assert 0 < distances[-1] < distances[0] < 30


def test_margin_call_cells_have_negative_excess_liquidity():
    grid = leveraged_grid(45)
    distance = grid.margin.distance_to_margin_call_percent
    for cell in grid.realistic_path:
        if -cell.spy_move_percent < distance - 1e-6:
            assert cell.excess_liquidity > 0
        else:
            assert cell.excess_liquidity <= 0


def test_unpriced_groups_add_no_margin_and_are_counted():
    naked = opt("UBER", "C", 120, -1, 150)
    held = stock("XYZ", 100, 50.0)
    market = AnalysisMarketData(by_con_id={held.con_id: {"last": 40.0}}, underlyings={})
    betas = {symbol: ResolvedBeta(symbol, 1.0, "computed", 252) for symbol in ("UBER", "XYZ")}
    exposure = build([naked, held], market, betas, PortfolioAccountSummary(account="U1"))

    grid = build_stress_grid(exposure.underlyings, None, 5_000, now=NOW, risk_free_rate=RATE)

    assert grid.margin.model_margin == pytest.approx(0.25 * 100 * 40)
    assert grid.margin.excluded_groups == 1
    assert grid.margin.calibration_factor == pytest.approx(5.0)
    assert grid.margin.distance_to_margin_call_percent is None
    assert grid.margin.margin_call_beyond_path is False
    assert all(cell.excess_liquidity is None for cell in grid.cells)
