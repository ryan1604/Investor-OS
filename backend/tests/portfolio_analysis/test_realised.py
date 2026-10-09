import math
import statistics
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.options.store import CompletedDailyBar
from app.portfolio.nav_store import DailyNav
from app.portfolio_analysis.realised import (
    NavPoint,
    build_realised_stats,
    daily_returns,
    drawdowns,
    nav_series,
    realised_beta,
    realised_volatility,
)
from tests.conftest import make_api
from tests.portfolio_analysis.test_api import connected_client


def weekdays(count: int, start: date = date(2025, 1, 2)) -> list[date]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def points(values: dict[date, float], currency: str = "USD") -> list[NavPoint]:
    return [NavPoint(day, nav, currency) for day, nav in values.items()]


def compound(days: list[date], returns: list[float], start: float = 100_000) -> dict[date, float]:
    values = {days[0]: start}
    for day, value in zip(days[1:], returns):
        values[day] = values[max(values)] * (1 + value)
    return values


def spy_bars(days: list[date], returns: list[float]) -> list[CompletedDailyBar]:
    return [
        CompletedDailyBar(
            ticker="SPY",
            trading_date=day.isoformat(),
            open=close,
            high=close,
            low=close,
            close=close,
        )
        for day, close in compound(days, returns, 500).items()
    ]


def market_returns(count: int) -> list[float]:
    return [
        0.01 * math.sin(index * 1.7) + 0.002 * math.cos(index * 0.3)
        for index in range(count)
    ]


def test_nav_series_drops_weekends_and_bad_navs_and_keeps_the_latest_currency_run():
    series = nav_series(
        [
            NavPoint(date(2026, 9, 25), 110, "USD"),
            NavPoint(date(2026, 9, 21), 90, "SGD"),
            NavPoint(date(2026, 9, 22), 100, "USD"),
            NavPoint(date(2026, 9, 26), 111, "USD"),  # Saturday
            NavPoint(date(2026, 9, 23), 0, "USD"),
            NavPoint(date(2026, 9, 24), 105, "USD"),
        ]
    )

    assert [(point.report_date.day, point.nav) for point in series] == [
        (22, 100),
        (24, 105),
        (25, 110),
    ]
    assert nav_series([]) == []


def test_daily_returns_span_weekends_and_one_holiday_but_not_longer_gaps():
    series = points(
        {
            date(2026, 9, 11): 100,  # Friday
            date(2026, 9, 14): 110,  # Monday: over the weekend
            date(2026, 9, 16): 121,  # Wednesday: one weekday (a holiday) skipped
            date(2026, 9, 21): 50,  # Monday: three weekdays missing
            date(2026, 9, 22): 55,
        }
    )

    assert daily_returns(series) == pytest.approx([0.1, 0.1, 0.1])


def test_realised_volatility_uses_the_latest_window_and_needs_enough_returns():
    calm = [0.01, -0.01] * 10
    returns = [0.2, -0.2] * 5 + calm

    result = realised_volatility(returns, 20)
    assert result.value == pytest.approx(statistics.stdev(calm) * math.sqrt(252) * 100)
    assert (result.observations, result.reason) == (20, None)

    short = realised_volatility(returns, 60)
    assert short.value is None
    assert short.observations == 30
    assert short.reason == "Needs 60 daily NAV returns; 30 available."


def test_drawdowns_from_the_running_peak():
    days = weekdays(5)
    max_drawdown, current = drawdowns(points(dict(zip(days, [100, 120, 90, 110, 115]))))
    assert max_drawdown.value == pytest.approx(-25)
    assert current.value == pytest.approx((115 / 120 - 1) * 100)
    assert max_drawdown.observations == 5

    _, at_peak = drawdowns(points(dict(zip(days, [100, 90, 130]))))
    assert at_peak.value == 0

    single_max, single_current = drawdowns(points({days[0]: 100}))
    assert single_max.value is None and single_current.value is None
    assert single_max.reason == "Needs at least 2 daily NAVs."


def test_realised_beta_matches_spy_through_gaps_and_holiday_rows():
    days = weekdays(260)
    market = market_returns(259)
    navs = compound(days, [1.5 * value for value in market])
    # NAV gaps drop dates; a holiday row with no SPY bar is ignored.
    for day in days[100:103]:
        del navs[day]
    christmas = date(2025, 12, 25)
    navs[christmas] = navs[max(day for day in navs if day < christmas)]
    spy = [bar for bar in spy_bars(days, market) if bar.trading_date != christmas.isoformat()]

    result = realised_beta(nav_series(points(navs)), spy)

    assert result.value == pytest.approx(1.5, abs=0.02)
    assert result.observations == 252
    assert result.reason is None


def test_realised_beta_needs_spy_bars_and_sixty_matched_returns():
    days = weekdays(40)
    series = points(compound(days, market_returns(39)))

    missing = realised_beta(series, None)
    assert (missing.value, missing.reason) == (None, "SPY daily bars are not available yet.")
    assert realised_beta(series, []).reason == "SPY daily bars are not available yet."

    short = realised_beta(series, spy_bars(days, market_returns(39)))
    assert short.value is None
    assert short.observations == 39
    assert short.reason == "Needs 60 daily NAV returns matched with SPY; 39 available."


def test_build_realised_stats_reports_the_window_and_reasons():
    empty = build_realised_stats([], None)
    assert (empty.currency, empty.start_date, empty.nav_observations) == (None, None, 0)
    assert empty.volatility_20d_percent.reason == "Needs 20 daily NAV returns; 0 available."
    assert empty.max_drawdown_percent.reason == "Needs at least 2 daily NAVs."

    days = weekdays(70)
    market = market_returns(69)
    stats = build_realised_stats(points(compound(days, market)), spy_bars(days, market))
    assert (stats.currency, stats.start_date, stats.end_date) == ("USD", days[0], days[-1])
    assert stats.nav_observations == 70
    assert stats.volatility_20d_percent.value is not None
    assert stats.volatility_60d_percent.observations == 60
    assert stats.beta.value == pytest.approx(1)


def test_analysis_response_includes_realised_stats_from_the_nav_store():
    portfolio_client = connected_client()
    api = make_api(portfolio_client)
    days = weekdays(30, start=date(2026, 8, 3))
    navs = compound(days, [0.01, -0.005] * 15)

    with TestClient(api) as client:
        api.state.portfolio_nav_store.upsert_values(
            [
                DailyNav(
                    account="DU1234567",
                    report_date=day.isoformat(),
                    nav=Decimal(f"{nav:.2f}"),
                    currency="USD",
                    source="flex",
                )
                for day, nav in navs.items()
            ]
        )
        portfolio_client.allow_refresh.set()
        with client.websocket_connect("/portfolio/ws") as portfolio_ws:
            while not portfolio_ws.receive_json()["status"]["connected"]:
                pass
        response = client.get("/portfolio/analysis", params={"account": "DU1234567"})

    realised = response.json()["realised"]
    assert realised["nav_observations"] == 30
    assert realised["start_date"] == "2026-08-03"
    assert realised["volatility_20d_percent"]["value"] > 0
    assert realised["volatility_60d_percent"]["reason"] == (
        "Needs 60 daily NAV returns; 29 available."
    )
    assert realised["max_drawdown_percent"]["value"] == pytest.approx(-0.5, abs=0.01)
    # The test app has no IB bar provider, so SPY bars are never available.
    assert realised["beta"]["reason"] == "SPY daily bars are not available yet."
