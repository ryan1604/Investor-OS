import time

import pytest
from test_portfolio_analysis_exposure import NOW, RATE, build, fixture_portfolio, opt, stock

from app.ib.portfolio import AnalysisMarketData
from app.portfolio_analysis.beta import ResolvedBeta
from app.portfolio_analysis.stress import (
    IV_SHOCKS,
    REALISTIC_PATH,
    SPY_MOVES,
    build_stress_grid,
    scenario_pnl,
    shocked_spot,
    shocked_volatility,
    stress_legs,
)
from app.schemas import PortfolioAccountSummary

DOWNSIDE_CELLS = [
    (move, shock) for move in SPY_MOVES if move < 0 for shock in IV_SHOCKS
]
ALL_CELLS = [(move, shock) for move in SPY_MOVES for shock in IV_SHOCKS]
VERTICALS = {
    "put_credit_spread": "credit",
    "call_credit_spread": "credit",
    "put_debit_spread": "debit",
    "call_debit_spread": "debit",
}


def fixture_exposure():
    return build(*fixture_portfolio())


def grid_for(exposure, net_liquidation=100_000):
    return build_stress_grid(exposure.underlyings, net_liquidation, None, now=NOW, risk_free_rate=RATE)


def group_legs(exposure, kind):
    underlying, group = next(
        (underlying, group)
        for underlying in exposure.underlyings
        for group in underlying.groups
        if group.kind == kind
    )
    legs, excluded = stress_legs(
        [underlying.model_copy(update={"groups": [group]})],
        now=NOW,
        risk_free_rate=RATE,
    )
    assert excluded == 0
    return group, legs


def test_grid_covers_every_cell_and_marks_the_realistic_path():
    grid = grid_for(fixture_exposure())

    assert grid.spy_moves_percent == pytest.approx([-30, -20, -15, -10, -5, 0, 5, 10])
    assert grid.iv_shocks_percent == pytest.approx([0, 25, 50, 100])
    assert len(grid.cells) == len(SPY_MOVES) * len(IV_SHOCKS)
    assert (grid.legs, grid.excluded_legs) == (20, 0)
    assert [
        (cell.spy_move_percent, cell.iv_shock_percent) for cell in grid.realistic_path
    ] == pytest.approx([(move * 100, shock * 100) for move, shock in REALISTIC_PATH])
    assert all(cell.realistic_path for cell in grid.realistic_path)
    marked = [
        (cell.spy_move_percent, cell.iv_shock_percent)
        for cell in grid.cells
        if cell.realistic_path
    ]
    assert marked == pytest.approx([(-30, 100)])
    for cell in grid.cells + grid.realistic_path:
        assert cell.pnl_percent == pytest.approx(cell.pnl / 100_000 * 100)


def test_no_shock_cell_has_zero_pnl():
    grid = grid_for(fixture_exposure())

    zero = next(
        cell for cell in grid.cells if cell.spy_move_percent == 0 and cell.iv_shock_percent == 0
    )
    assert zero.pnl == pytest.approx(0, abs=1e-6)
    assert zero.pnl_percent == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize(("kind", "sign"), [("long_put", 1), ("short_put", -1)])
def test_long_puts_gain_and_short_puts_lose_on_downside_and_vol_up(kind, sign):
    _, legs = group_legs(fixture_exposure(), kind)

    for move, shock in DOWNSIDE_CELLS:
        assert sign * scenario_pnl(legs, move, shock, RATE) > 0, (move, shock)
    for shock in IV_SHOCKS[1:]:
        assert sign * scenario_pnl(legs, 0.0, shock, RATE) > 0, shock


@pytest.mark.parametrize("kind", VERTICALS)
def test_spreads_never_lose_more_than_their_remaining_max_loss(kind):
    group, legs = group_legs(fixture_exposure(), kind)
    strikes = sorted(leg.strike for leg in legs)
    width = (strikes[1] - strikes[0]) * 100 * group.quantity
    current_value = sum(leg.base_value * leg.quantity * 100 for leg in legs)
    # From here, a credit spread can at worst be worth -width and a debit spread 0.
    lowest_value = -width if VERTICALS[kind] == "credit" else 0.0
    remaining_max_loss = current_value - lowest_value

    assert 0 < remaining_max_loss <= width
    for move, shock in ALL_CELLS:
        assert scenario_pnl(legs, move, shock, RATE) >= -remaining_max_loss - 1e-6


def test_stock_pnl_is_linear_in_beta_with_fx_and_the_downside_floor():
    exposure = fixture_exposure()
    _, aapl = group_legs(exposure, "stock")  # 100 spare AAPL shares at 200, beta 1.2
    assert scenario_pnl(aapl, -0.10, 0.5, RATE) == pytest.approx(100 * 200 * -0.12)

    d05 = next(underlying for underlying in exposure.underlyings if underlying.symbol == "D05")
    legs, _ = stress_legs([d05], now=NOW, risk_free_rate=RATE)
    assert scenario_pnl(legs, 0.10, 0.0, RATE) == pytest.approx(100 * 40 * 0.15 * 0.75)

    assert shocked_spot(50.0, 4.0, -0.30) == pytest.approx(2.5)
    assert shocked_spot(50.0, -1.0, -0.30) == pytest.approx(65.0)


def test_iv_shock_scales_with_beta_floor_and_puts():
    assert shocked_volatility(0.4, "C", 1.5, 0.5) == pytest.approx(0.4 * 1.75)
    assert shocked_volatility(0.4, "P", 1.5, 0.5) == pytest.approx(0.4 * 1.9)
    assert shocked_volatility(0.4, "C", 0.2, 1.0) == pytest.approx(0.4 * 1.5)
    assert shocked_volatility(0.4, "P", -1.0, 1.0) == pytest.approx(0.4 * 1.6)
    assert shocked_volatility(0.4, "C", 2.0, 0.0) == pytest.approx(0.4)


def test_legs_without_price_or_iv_are_counted_and_left_out():
    naked = opt("UBER", "C", 120, -1, 150)
    no_price = stock("XYZ", 10, 5.0)
    market = AnalysisMarketData(by_con_id={}, underlyings={"UBER": {"last": 100.0}})
    betas = {symbol: ResolvedBeta(symbol, 1.0, "computed", 252) for symbol in ("UBER", "XYZ")}
    exposure = build([naked, no_price], market, betas, PortfolioAccountSummary(account="U1"))

    grid = grid_for(exposure, net_liquidation=None)

    assert (grid.legs, grid.excluded_legs) == (0, 2)
    assert all(cell.pnl == 0 and cell.pnl_percent is None for cell in grid.cells)


def test_a_spread_with_an_unpriced_leg_is_left_out_whole():
    short_put = opt("UBER", "P", 100, -1, 300)
    long_put = opt("UBER", "P", 90, 1, 100)
    market = AnalysisMarketData(
        by_con_id={short_put.con_id: {"implied_volatility": 0.4}},
        underlyings={"UBER": {"last": 100.0}},
    )
    betas = {"UBER": ResolvedBeta("UBER", 1.0, "computed", 252)}
    exposure = build([short_put, long_put], market, betas, PortfolioAccountSummary(account="U1"))
    [group] = exposure.underlyings[0].groups
    assert group.kind == "put_credit_spread"

    grid = grid_for(exposure)
    legs, excluded = stress_legs(exposure.underlyings, now=NOW, risk_free_rate=RATE)

    # Not stressed as a naked short put.
    assert (grid.legs, grid.excluded_legs) == (0, 2)
    assert (legs, excluded) == ([], 2)
    assert grid.margin.excluded_groups == 1
    assert all(cell.pnl == 0 for cell in grid.cells)


def test_grid_computes_within_100ms_for_100_positions():
    positions, market, betas, summary = fixture_portfolio()
    options = [position for position in positions if position.sec_type == "OPT"]
    extra = []
    for index in range(100 - len(options) - 2):
        template = options[index % len(options)]
        extra.append(opt(template.symbol, template.right, template.strike + index % 7, 1))
        market.by_con_id[extra[-1].con_id] = market.by_con_id.get(template.con_id, {}) | {
            "implied_volatility": 0.4,
        }
    exposure = build(positions + extra, market, betas, summary)
    legs, _ = stress_legs(exposure.underlyings, now=NOW, risk_free_rate=RATE)
    assert len(legs) >= 100

    elapsed = min(_timed(lambda: grid_for(exposure)) for _ in range(3))

    assert elapsed < 0.1


def _timed(action):
    started = time.perf_counter()
    action()
    return time.perf_counter() - started
