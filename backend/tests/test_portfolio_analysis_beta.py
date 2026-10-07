import random
import statistics
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ib.app import IbPortfolioApp
from app.options.client import OptionsDataUnavailable
from app.options.store import CompletedDailyBar
from app.portfolio_analysis.beta import (
    BETA_LOOKBACK_DAYS,
    FAILED_FETCH_RETRY_SECONDS,
    TRUNCATED_FETCH_ATTEMPTS,
    BetaService,
    compute_beta,
)
from app.portfolio_analysis.beta_store import BetaEstimate, BetaStore
from app.portfolio_analysis.sessions import us_session_date
from app.schemas import BetaOverrideRequest
from conftest import make_api


def business_days(count: int, start: date = date(2025, 1, 2)) -> list[date]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def bars_from_closes(ticker: str, closes: dict[date, float]) -> list[CompletedDailyBar]:
    return [
        CompletedDailyBar(
            ticker=ticker,
            trading_date=day.isoformat(),
            open=close,
            high=close,
            low=close,
            close=close,
        )
        for day, close in closes.items()
    ]


def bars_from_returns(ticker: str, days: list[date], returns: list[float]) -> list[CompletedDailyBar]:
    closes = {days[0]: 100.0}
    for day, value in zip(days[1:], returns):
        closes[day] = closes[max(closes)] * (1 + value)
    return bars_from_closes(ticker, closes)


def spy_returns(count: int, seed: int = 7) -> list[float]:
    generator = random.Random(seed)
    return [generator.gauss(0.0005, 0.01) for _ in range(count)]


@pytest.mark.parametrize("beta", [1.5, -0.5, 0.0])
def test_compute_beta_recovers_exact_linear_beta(beta):
    days = business_days(253)
    market = spy_returns(252)
    estimate = compute_beta(
        bars_from_returns("X", days, [beta * value for value in market]),
        bars_from_returns("SPY", days, market),
    )
    assert estimate.beta == pytest.approx(beta, abs=1e-9)
    assert estimate.observations == 252


def test_compute_beta_matches_reference_regression_with_noise():
    days = business_days(200)
    market = spy_returns(199)
    noise = random.Random(3)
    ticker = [1.2 * value + noise.gauss(0, 0.02) for value in market]
    estimate = compute_beta(
        bars_from_returns("X", days, ticker),
        bars_from_returns("SPY", days, market),
    )
    expected = statistics.covariance(ticker, market) / statistics.variance(market)
    assert estimate.beta == pytest.approx(expected, rel=1e-9)
    assert estimate.observations == 199


def test_compute_beta_uses_only_latest_252_returns():
    days = business_days(401)
    market = spy_returns(400)
    ticker = [0.5 * value for value in market[:148]] + [2.0 * value for value in market[148:]]
    estimate = compute_beta(
        bars_from_returns("X", days, ticker),
        bars_from_returns("SPY", days, market),
    )
    assert estimate.beta == pytest.approx(2.0)
    assert estimate.observations == 252


def test_compute_beta_requires_sixty_observations():
    days = business_days(61)
    market = spy_returns(60)
    enough = compute_beta(
        bars_from_returns("X", days, market),
        bars_from_returns("SPY", days, market),
    )
    short = compute_beta(
        bars_from_returns("X", days[:60], market[:59]),
        bars_from_returns("SPY", days, market),
    )
    assert enough == BetaEstimate(beta=pytest.approx(1.0), observations=60)
    assert short == BetaEstimate(beta=None, observations=59)


def test_compute_beta_aligns_misaligned_dates():
    days = business_days(150)
    market_closes = dict(
        (bar_date, bar.close)
        for bar_date, bar in zip(days, bars_from_returns("SPY", days, spy_returns(149)))
    )
    # The ticker tracks SPY exactly on shared dates but skips every fifth session.
    ticker_closes = {day: close * 0.4 for index, (day, close) in enumerate(market_closes.items()) if index % 5}
    # Dates only one series has carry wild prices that must be ignored.
    spy_bars = bars_from_closes("SPY", market_closes) + bars_from_closes(
        "SPY", {date(2025, 1, 4): 1.0},
    )
    ticker_bars = bars_from_closes("X", ticker_closes) + bars_from_closes(
        "X", {date(2025, 1, 5): 999.0},
    )
    estimate = compute_beta(ticker_bars, spy_bars)
    assert estimate.beta == pytest.approx(1.0)
    assert estimate.observations == len(ticker_closes) - 1


def test_compute_beta_handles_flat_benchmark_and_bad_closes():
    days = business_days(100)
    flat = bars_from_closes("SPY", {day: 400.0 for day in days})
    ticker = bars_from_returns("X", days, spy_returns(99))
    assert compute_beta(ticker, flat) == BetaEstimate(beta=None, observations=99)

    zero_closes = bars_from_closes("X", {day: 0.0 for day in days})
    assert compute_beta(zero_closes, ticker) == BetaEstimate(beta=None, observations=0)


def test_session_date_rolls_weekends_back_to_friday():
    assert us_session_date(datetime(2026, 9, 25, 23, 0, tzinfo=UTC)) == date(2026, 9, 25)
    assert us_session_date(datetime(2026, 9, 26, 15, 0, tzinfo=UTC)) == date(2026, 9, 25)
    assert us_session_date(datetime(2026, 9, 28, 3, 0, tzinfo=UTC)) == date(2026, 9, 25)
    assert us_session_date(datetime(2026, 9, 28, 14, 0, tzinfo=UTC)) == date(2026, 9, 28)


class FakeBarProvider:
    def __init__(self, series: dict[str, list[CompletedDailyBar]]) -> None:
        self.series = series
        self.requests: list[tuple[str, date, date]] = []
        self.errors: dict[str, Exception] = {}
        # (ticker, chunk start) pairs that time out, returning no bars like IB.
        self.timeouts: set[tuple[str, date]] = set()

    def fetch_daily_bars(self, ticker, start_date, end_date):
        self.requests.append((ticker, start_date, end_date))
        if ticker in self.errors:
            raise self.errors[ticker]
        if (ticker, start_date) in self.timeouts:
            return []
        return [
            bar
            for bar in self.series.get(ticker, [])
            if start_date.isoformat() <= bar.trading_date <= end_date.isoformat()
        ]

    def tickers(self) -> list[str]:
        return [ticker for ticker, _, _ in self.requests]


SESSION_NOW = datetime(2026, 9, 25, 18, 0, tzinfo=UTC)


def market_series() -> dict[str, list[CompletedDailyBar]]:
    days = business_days(300, start=date(2025, 7, 1))
    market = spy_returns(299)
    return {
        "SPY": bars_from_returns("SPY", days, market),
        "HIMS": bars_from_returns("HIMS", days, [2 * value for value in market]),
        "NEW": bars_from_returns("NEW", days[-30:], [2 * value for value in market[-29:]]),
    }


class Clock:
    def __init__(self) -> None:
        self.now = SESSION_NOW
        self.seconds = 0.0


def current_series() -> dict[str, list[CompletedDailyBar]]:
    """Bars up to the session, so both lookback chunks hold bars."""
    days = [day for day in business_days(320, start=date(2025, 7, 1)) if day <= date(2026, 9, 25)]
    market = spy_returns(len(days) - 1)
    return {
        "SPY": bars_from_returns("SPY", days, market),
        "HIMS": bars_from_returns("HIMS", days, [2 * value for value in market]),
    }


LOOKBACK_START = date(2026, 9, 25) - timedelta(days=BETA_LOOKBACK_DAYS)
RECENT_CHUNK_START = LOOKBACK_START + timedelta(days=365)


def beta_service(tmp_path, provider, clock: Clock | None = None):
    clock = clock or Clock()
    store = BetaStore(tmp_path / "analysis.sqlite3")
    return BetaService(
        store,
        provider,
        now=lambda: clock.now,
        clock=lambda: clock.seconds,
    ), store, clock


def test_resolve_computes_caches_and_flags_short_history(tmp_path):
    provider = FakeBarProvider(market_series())
    service, store, _ = beta_service(tmp_path, provider)

    resolved = service.resolve(["hims", "NEW", "SPY"])

    assert resolved["HIMS"].beta == pytest.approx(2.0)
    assert resolved["HIMS"].source == "computed"
    assert resolved["SPY"].beta == pytest.approx(1.0)
    assert resolved["NEW"].beta == 1.0
    # Short history looks truncated, so it is retried before being cached.
    assert resolved["NEW"].is_fallback and resolved["NEW"].pending
    assert provider.tickers() == ["SPY", "SPY", "HIMS", "HIMS", "NEW", "NEW"]
    assert provider.requests[0][1] == date(2026, 9, 25) - timedelta(days=BETA_LOOKBACK_DAYS)
    assert provider.requests[-1][2] == date(2026, 9, 25)
    assert set(store.cached_betas("2026-09-25")) == {"HIMS", "SPY"}


def test_resolve_refreshes_once_per_session(tmp_path):
    provider = FakeBarProvider(market_series())
    service, _, clock = beta_service(tmp_path, provider)

    service.resolve(["HIMS", "SPY"])
    requests = len(provider.requests)
    again = service.resolve(["HIMS", "SPY"])
    assert len(provider.requests) == requests
    assert again["HIMS"].source == "computed"
    assert again["SPY"].source == "computed"

    clock.now = SESSION_NOW + timedelta(days=1)
    service.resolve(["HIMS"])
    assert len(provider.requests) == requests

    clock.now = SESSION_NOW + timedelta(days=3)
    service.resolve(["HIMS"])
    assert provider.tickers()[requests:] == ["SPY", "SPY", "HIMS", "HIMS"]


def test_override_takes_precedence_over_cached_and_computed_beta(tmp_path):
    provider = FakeBarProvider(market_series())
    service, store, _ = beta_service(tmp_path, provider)
    service.resolve(["HIMS"])

    store.set_override("HIMS", 0.8)
    store.set_override("SOFI", 1.7)
    requests = len(provider.requests)
    resolved = service.resolve(["HIMS", "SOFI"])

    assert (resolved["HIMS"].beta, resolved["HIMS"].source) == (0.8, "override")
    assert (resolved["SOFI"].beta, resolved["SOFI"].source) == (1.7, "override")
    assert len(provider.requests) == requests

    store.delete_override("HIMS")
    assert service.resolve(["HIMS"])["HIMS"].beta == pytest.approx(2.0)


def test_missing_benchmark_falls_back_without_caching_and_retries_later(tmp_path):
    provider = FakeBarProvider({})
    service, store, clock = beta_service(tmp_path, provider)

    resolved = service.resolve(["HIMS"])
    assert resolved["HIMS"].is_fallback
    assert store.cached_betas("2026-09-25") == {}

    service.resolve(["HIMS"])
    assert provider.tickers() == ["SPY", "SPY"]

    provider.series = market_series()
    clock.seconds = FAILED_FETCH_RETRY_SECONDS
    assert service.resolve(["HIMS"])["HIMS"].source == "computed"


def test_invalid_ticker_is_cached_as_fallback(tmp_path):
    provider = FakeBarProvider(market_series())
    provider.errors["BAD"] = OptionsDataUnavailable("Invalid ticker: BAD.")
    service, _, _ = beta_service(tmp_path, provider)

    assert service.resolve(["BAD"])["BAD"].is_fallback
    service.resolve(["BAD"])
    assert provider.tickers().count("BAD") == 1


def test_failed_fetch_falls_back_and_retries_after_pause(tmp_path):
    provider = FakeBarProvider(market_series())
    provider.errors["HIMS"] = TimeoutError("IB timed out")
    service, store, clock = beta_service(tmp_path, provider)

    assert service.resolve(["HIMS"])["HIMS"].is_fallback
    assert "HIMS" not in store.cached_betas("2026-09-25")
    service.resolve(["HIMS"])
    assert provider.tickers().count("HIMS") == 1

    del provider.errors["HIMS"]
    clock.seconds = FAILED_FETCH_RETRY_SECONDS
    assert service.resolve(["HIMS"])["HIMS"].source == "computed"


@pytest.mark.parametrize("chunk_start", [LOOKBACK_START, RECENT_CHUNK_START])
def test_a_timed_out_chunk_is_retried_instead_of_cached(tmp_path, chunk_start):
    provider = FakeBarProvider(current_series())
    provider.timeouts.add(("HIMS", chunk_start))
    service, store, clock = beta_service(tmp_path, provider)

    resolved = service.resolve(["HIMS"])
    assert resolved["HIMS"].is_fallback and resolved["HIMS"].pending
    assert "HIMS" not in store.cached_betas("2026-09-25")
    service.resolve(["HIMS"])
    assert provider.tickers().count("HIMS") == 2

    provider.timeouts.clear()
    clock.seconds = FAILED_FETCH_RETRY_SECONDS
    resolved = service.resolve(["HIMS"])
    assert (resolved["HIMS"].source, resolved["HIMS"].observations) == ("computed", 252)
    assert resolved["HIMS"].beta == pytest.approx(2.0)


def test_an_older_chunk_returning_only_its_tail_is_retried(tmp_path):
    # Seen live for QQQ: the older chunk sent its last few bars, leaving 16 in all.
    series = current_series()
    # Starts before RECENT_CHUNK_START, so the older chunk is not empty.
    tail = [bar for bar in series["HIMS"] if bar.trading_date >= "2026-09-04"]
    provider = FakeBarProvider({**series, "HIMS": tail})
    service, store, clock = beta_service(tmp_path, provider)

    assert service.resolve(["HIMS"])["HIMS"].pending
    assert "HIMS" not in store.cached_betas("2026-09-25")

    provider.series = series
    clock.seconds = FAILED_FETCH_RETRY_SECONDS
    assert service.resolve(["HIMS"])["HIMS"].observations == 252


def test_bars_that_stay_short_are_cached_after_the_retry_limit(tmp_path):
    series = current_series()
    # Listed inside the recent chunk, so the older chunk is genuinely empty.
    series["NEW"] = series["HIMS"][-5:]
    provider = FakeBarProvider(series)
    service, store, clock = beta_service(tmp_path, provider)

    for attempt in range(TRUNCATED_FETCH_ATTEMPTS):
        clock.seconds = attempt * FAILED_FETCH_RETRY_SECONDS
        resolved = service.resolve(["NEW"])
    assert resolved["NEW"].is_fallback and not resolved["NEW"].pending
    assert store.cached_betas("2026-09-25")["NEW"].observations == 4
    assert provider.tickers().count("NEW") == 2 * TRUNCATED_FETCH_ATTEMPTS

    clock.seconds += FAILED_FETCH_RETRY_SECONDS
    assert not service.resolve(["NEW"], compute=False)["NEW"].pending
    service.resolve(["NEW"])
    assert provider.tickers().count("NEW") == 2 * TRUNCATED_FETCH_ATTEMPTS


def test_only_uncached_betas_are_pending(tmp_path):
    provider = FakeBarProvider(market_series())
    provider.errors["BAD"] = OptionsDataUnavailable("Invalid ticker: BAD.")
    service, _, _ = beta_service(tmp_path, provider)

    before = service.resolve(["HIMS", "BAD"], compute=False)
    assert before["HIMS"].pending and before["BAD"].pending
    service.resolve(["HIMS", "BAD"])
    after = service.resolve(["HIMS", "BAD"], compute=False)
    # A cached fallback is final for the session, so it needs no background fetch.
    assert after["BAD"].is_fallback and not after["BAD"].pending
    assert not after["HIMS"].pending


def test_benchmark_bars_are_fetched_once_per_session_and_shared_with_betas(tmp_path):
    provider = FakeBarProvider(market_series())
    service, _, clock = beta_service(tmp_path, provider)

    assert service.benchmark_bars(compute=False) is None
    assert provider.requests == []
    bars = service.benchmark_bars()
    assert bars and {bar.ticker for bar in bars} == {"SPY"}
    spy_requests = provider.tickers().count("SPY")
    assert service.benchmark_bars(compute=False) is bars
    # Beta computation reuses the session's SPY bars.
    assert service.resolve(["HIMS"])["HIMS"].source == "computed"
    assert provider.tickers().count("SPY") == spy_requests
    assert "HIMS" in provider.tickers()

    clock.now = SESSION_NOW + timedelta(days=3)
    assert service.benchmark_bars(compute=False) is None
    service.benchmark_bars()
    assert provider.tickers().count("SPY") == 2 * spy_requests


def test_partial_benchmark_bars_count_as_a_failed_fetch(tmp_path):
    series = market_series()
    # A timed-out chunk leaves only the latest few SPY bars.
    series["SPY"] = series["SPY"][-16:]
    provider = FakeBarProvider(series)
    service, store, clock = beta_service(tmp_path, provider)

    assert service.benchmark_bars() is None
    assert service.resolve(["HIMS"])["HIMS"].is_fallback
    assert store.cached_betas("2026-09-25") == {}

    provider.series = market_series()
    clock.seconds = FAILED_FETCH_RETRY_SECONDS
    assert service.benchmark_bars()
    assert service.resolve(["HIMS"])["HIMS"].source == "computed"


def test_missing_benchmark_bars_are_not_cached_and_retry_after_pause(tmp_path):
    provider = FakeBarProvider({})
    service, _, clock = beta_service(tmp_path, provider)

    assert service.benchmark_bars() is None
    requests = len(provider.requests)
    assert service.benchmark_bars() is None
    assert len(provider.requests) == requests

    provider.series = market_series()
    clock.seconds = FAILED_FETCH_RETRY_SECONDS
    assert service.benchmark_bars()


def test_resolve_without_provider_falls_back(tmp_path):
    service, _, _ = beta_service(tmp_path, None)
    resolved = service.resolve(["HIMS", ""])
    assert list(resolved) == ["HIMS"]
    assert resolved["HIMS"].is_fallback


def test_historical_requests_are_paced(monkeypatch):
    app = IbPortfolioApp()
    waits = []
    monkeypatch.setattr(app.message_pacer, "wait", lambda: waits.append(1))
    monkeypatch.setattr("ibapi.client.EClient.reqHistoricalData", lambda *args: None)

    app.reqHistoricalData(60_000, None, "", "1 D", "1 day", "TRADES", 1, 1, False, [])

    assert waits == [1]


def test_beta_overrides_persist_across_restarts(tmp_path):
    database_path = tmp_path / "analysis.sqlite3"
    with TestClient(make_api(portfolio_analysis_database_path=database_path)) as client:
        saved = client.put("/portfolio/analysis/beta-overrides/hims", json={"beta": 1.8})
        client.put("/portfolio/analysis/beta-overrides/AMD", json={"beta": -0.25})

    assert saved.status_code == 200
    assert saved.json()["ticker"] == "HIMS"
    assert saved.json()["beta"] == 1.8

    with TestClient(make_api(portfolio_analysis_database_path=database_path)) as client:
        listed = client.get("/portfolio/analysis/beta-overrides")
        cleared = client.delete("/portfolio/analysis/beta-overrides/hims")
        missing = client.delete("/portfolio/analysis/beta-overrides/HIMS")
        remaining = client.get("/portfolio/analysis/beta-overrides")

    assert [(row["ticker"], row["beta"]) for row in listed.json()] == [
        ("AMD", -0.25),
        ("HIMS", 1.8),
    ]
    assert cleared.status_code == 204
    assert missing.status_code == 404
    assert [row["ticker"] for row in remaining.json()] == ["AMD"]


@pytest.mark.parametrize("payload", [{"beta": 11}, {"beta": "abc"}, {}, {"beta": 1, "x": 2}])
def test_beta_override_rejects_invalid_values(tmp_path, payload):
    with TestClient(make_api(portfolio_analysis_database_path=tmp_path / "a.sqlite3")) as client:
        response = client.put("/portfolio/analysis/beta-overrides/HIMS", json=payload)
        listed = client.get("/portfolio/analysis/beta-overrides")
    assert response.status_code == 422
    assert listed.json() == []


@pytest.mark.parametrize("beta", [float("inf"), float("-inf"), float("nan")])
def test_beta_override_rejects_non_finite_values(beta):
    with pytest.raises(ValidationError):
        BetaOverrideRequest(beta=beta)


@pytest.mark.parametrize("raw", ["Infinity", "-Infinity", "NaN"])
def test_beta_override_api_rejects_non_finite_json(tmp_path, raw):
    with TestClient(make_api(portfolio_analysis_database_path=tmp_path / "a.sqlite3")) as client:
        response = client.put(
            "/portfolio/analysis/beta-overrides/HIMS",
            content=f'{{"beta": {raw}}}',
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] in ("inf", "-inf", "nan")


def test_beta_override_requires_ticker(tmp_path):
    with TestClient(make_api(portfolio_analysis_database_path=tmp_path / "a.sqlite3")) as client:
        response = client.put("/portfolio/analysis/beta-overrides/%20", json={"beta": 1})
    assert response.status_code == 400
