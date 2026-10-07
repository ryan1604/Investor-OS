"""Beta to SPY from daily closes, with overrides and a once-per-session cache."""

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from typing import Literal

from app.options.client import (
    HistoricalDailyBarProvider,
    OptionsDataUnavailable,
    fetch_chunked_daily_bars,
)
from app.options.store import CompletedDailyBar
from app.portfolio_analysis.beta_store import BetaEstimate, BetaStore
from app.portfolio_analysis.sessions import us_session_date
from app.tickers import normalize_ticker

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "SPY"
MIN_BETA_OBSERVATIONS = 60
MAX_BETA_OBSERVATIONS = 252
FALLBACK_BETA = 1.0
# 252 trading days span about 366 calendar days; the margin covers holidays.
BETA_LOOKBACK_DAYS = 380
FAILED_FETCH_RETRY_SECONDS = 60
# Bars that look cut short are refetched this many times per session before they
# are accepted as the ticker's real history (a recent IPO, a halt, another calendar).
TRUNCATED_FETCH_ATTEMPTS = 3
MAX_MISSING_BENCHMARK_DATES = 5

BetaSource = Literal["override", "computed", "fallback"]


@dataclass(frozen=True)
class ResolvedBeta:
    ticker: str
    beta: float
    source: BetaSource
    observations: int | None = None
    # True for a fallback not yet computed this session, as opposed to a cached result.
    pending: bool = False

    @property
    def is_fallback(self) -> bool:
        return self.source == "fallback"


def compute_beta(
    bars: Iterable[CompletedDailyBar],
    benchmark_bars: Iterable[CompletedDailyBar],
) -> BetaEstimate:
    """Regress daily returns on the benchmark over their common trading dates."""
    return regress_beta(closes_by_date(bars), closes_by_date(benchmark_bars))


def regress_beta(
    closes: dict[str, float],
    benchmark_closes: dict[str, float],
) -> BetaEstimate:
    """Beta from closes keyed by ISO date; a return spans consecutive common dates."""
    dates = sorted(closes.keys() & benchmark_closes.keys())
    returns = [
        (
            closes[current] / closes[previous] - 1,
            benchmark_closes[current] / benchmark_closes[previous] - 1,
        )
        for previous, current in zip(dates, dates[1:])
    ][-MAX_BETA_OBSERVATIONS:]
    observations = len(returns)
    if observations < MIN_BETA_OBSERVATIONS:
        return BetaEstimate(beta=None, observations=observations)

    mean = sum(value for value, _ in returns) / observations
    benchmark_mean = sum(value for _, value in returns) / observations
    covariance = sum(
        (value - mean) * (benchmark - benchmark_mean) for value, benchmark in returns
    )
    variance = sum((benchmark - benchmark_mean) ** 2 for _, benchmark in returns)
    if variance <= 0:
        return BetaEstimate(beta=None, observations=observations)
    return BetaEstimate(beta=covariance / variance, observations=observations)


def closes_by_date(bars: Iterable[CompletedDailyBar]) -> dict[str, float]:
    return {bar.trading_date: bar.close for bar in bars if bar.close > 0}


def looks_truncated(
    bars: Iterable[CompletedDailyBar],
    benchmark_bars: Iterable[CompletedDailyBar],
) -> bool:
    """True when bars miss SPY's latest session or more than a few of its dates.

    The bar provider returns partial or no bars on a timeout instead of failing,
    and a chunk can come back with only some of its bars. Real short history looks
    the same, so callers accept it after a few attempts.
    """
    dates = {bar.trading_date for bar in bars}
    benchmark_dates = {bar.trading_date for bar in benchmark_bars}
    if not benchmark_dates:
        return False
    if not dates or max(dates) < max(benchmark_dates):
        return True
    return len(benchmark_dates - dates) > MAX_MISSING_BENCHMARK_DATES


class BetaService:
    """Resolve beta as override, today's cached value, fresh computation, or 1.0."""

    def __init__(
        self,
        store: BetaStore,
        provider: HistoricalDailyBarProvider | None,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.store = store
        self.provider = provider
        self.now = now
        self.clock = clock
        self.retry_after = 0.0
        # Ticker -> (session, truncated fetches so far).
        self.truncated_fetches: dict[str, tuple[date, int]] = {}
        self.lock = threading.Lock()
        # The session's SPY bars, kept for the portfolio's realised beta.
        self.benchmark: tuple[date, list[CompletedDailyBar]] | None = None

    def resolve(
        self,
        tickers: Iterable[str],
        *,
        compute: bool = True,
    ) -> dict[str, ResolvedBeta]:
        """Resolve betas; with compute=False, unknown tickers fall back without IB calls."""
        session = us_session_date(self.now())
        normalized = sorted({normalize_ticker(ticker) for ticker in tickers} - {""})
        resolved, missing = self._known(normalized, session)
        if compute and missing:
            with self.lock:
                # Another thread may have computed these while this one waited.
                known, missing = self._known(missing, session)
                resolved.update(known)
                if missing and self.clock() >= self.retry_after:
                    resolved.update(self._compute(missing, session))
        for ticker in missing:
            resolved.setdefault(
                ticker, ResolvedBeta(ticker, FALLBACK_BETA, "fallback", 0, pending=True)
            )
        return resolved

    def benchmark_bars(self, *, compute: bool = True) -> list[CompletedDailyBar] | None:
        """This session's SPY bars; with compute=False, None until they are fetched."""
        session = us_session_date(self.now())
        cached = self._cached_benchmark(session)
        if cached is not None or not compute:
            return cached
        with self.lock:
            cached = self._cached_benchmark(session)
            if cached is None and self.clock() >= self.retry_after:
                cached = self._fetch_benchmark(session)
        return cached

    def _cached_benchmark(self, session: date) -> list[CompletedDailyBar] | None:
        benchmark = self.benchmark
        return benchmark[1] if benchmark is not None and benchmark[0] == session else None

    def _fetch_benchmark(self, session: date) -> list[CompletedDailyBar] | None:
        bars = self._fetch_bars(BENCHMARK_TICKER, session)
        if bars is None or len(bars) <= MIN_BETA_OBSERVATIONS:
            # SPY always trades, so missing or partial bars (a timed-out chunk)
            # mean IB is unavailable; retry after a pause instead of caching them.
            self.retry_after = self.clock() + FAILED_FETCH_RETRY_SECONDS
            return None
        self.benchmark = (session, bars)
        return bars

    def _known(
        self,
        tickers: list[str],
        session: date,
    ) -> tuple[dict[str, ResolvedBeta], list[str]]:
        overrides = self.store.override_betas()
        cached = self.store.cached_betas(session.isoformat())
        resolved: dict[str, ResolvedBeta] = {}
        missing: list[str] = []
        for ticker in tickers:
            if ticker in overrides:
                resolved[ticker] = ResolvedBeta(ticker, overrides[ticker], "override")
            elif ticker in cached:
                resolved[ticker] = resolved_estimate(ticker, cached[ticker])
            else:
                missing.append(ticker)
        return resolved, missing

    def _compute(self, tickers: list[str], session: date) -> dict[str, ResolvedBeta]:
        benchmark_bars = self._cached_benchmark(session)
        if benchmark_bars is None:
            benchmark_bars = self._fetch_benchmark(session)
        if benchmark_bars is None:
            return {}

        resolved = {}
        for ticker in tickers:
            bars = (
                benchmark_bars
                if ticker == BENCHMARK_TICKER
                else self._fetch_bars(ticker, session, benchmark_bars)
            )
            if bars is None:
                self.retry_after = self.clock() + FAILED_FETCH_RETRY_SECONDS
                continue

            estimate = compute_beta(bars, benchmark_bars)
            self.store.save_cached_beta(ticker, session.isoformat(), estimate)
            resolved[ticker] = resolved_estimate(ticker, estimate)
            logger.info(
                "Portfolio analysis beta computed ticker=%s beta=%s observations=%s",
                ticker,
                estimate.beta,
                estimate.observations,
            )
        return resolved

    def _fetch_bars(
        self,
        ticker: str,
        session: date,
        benchmark_bars: list[CompletedDailyBar] | None = None,
    ) -> list[CompletedDailyBar] | None:
        """Return daily bars, [] when IB has none, or None when the request failed.

        With benchmark bars, bars that look truncated also count as a failed request.
        """
        if self.provider is None:
            return []
        start = session - timedelta(days=BETA_LOOKBACK_DAYS)
        try:
            bars = list(fetch_chunked_daily_bars(self.provider, ticker, [(start, session)]))
        except OptionsDataUnavailable:
            # An invalid ticker stays invalid, so it is cached as a fallback.
            return []
        except Exception:
            logger.warning("Could not fetch beta bars ticker=%s", ticker, exc_info=True)
            return None
        if benchmark_bars is not None and looks_truncated(bars, benchmark_bars):
            attempts = self._count_truncated_fetch(ticker, session)
            if attempts < TRUNCATED_FETCH_ATTEMPTS:
                logger.warning(
                    "Beta bars look truncated ticker=%s bars=%s attempt=%s",
                    ticker,
                    len(bars),
                    attempts,
                )
                return None
        return bars

    def _count_truncated_fetch(self, ticker: str, session: date) -> int:
        previous_session, attempts = self.truncated_fetches.get(ticker, (session, 0))
        attempts = attempts + 1 if previous_session == session else 1
        self.truncated_fetches[ticker] = (session, attempts)
        return attempts


def resolved_estimate(ticker: str, estimate: BetaEstimate) -> ResolvedBeta:
    if estimate.beta is None:
        return ResolvedBeta(ticker, FALLBACK_BETA, "fallback", estimate.observations)
    return ResolvedBeta(ticker, estimate.beta, "computed", estimate.observations)
