"""Realised risk statistics from the account's daily NAV history."""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.options.store import CompletedDailyBar
from app.portfolio_analysis.beta import (
    MIN_BETA_OBSERVATIONS,
    closes_by_date,
    regress_beta,
)
from app.schemas import AnalysisRealisedStats, AnalysisRealisedValue

TRADING_DAYS_PER_YEAR = 252
VOLATILITY_WINDOWS = (20, 60)
# A return may skip one weekday (a holiday); a longer gap is missing data.
MAX_SKIPPED_WEEKDAYS = 1


@dataclass(frozen=True)
class NavPoint:
    report_date: date
    nav: float
    currency: str


def nav_series(points: Iterable[NavPoint]) -> list[NavPoint]:
    """Positive weekday NAVs in date order, trimmed to the latest currency's run."""
    series = sorted(
        (point for point in points if point.nav > 0 and point.report_date.weekday() < 5),
        key=lambda point: point.report_date,
    )
    if not series:
        return []
    currency = series[-1].currency
    start = len(series)
    while start > 0 and series[start - 1].currency == currency:
        start -= 1
    return series[start:]


def skipped_weekdays(start: date, end: date) -> int:
    return sum(
        (start + timedelta(days=offset)).weekday() < 5
        for offset in range(1, (end - start).days)
    )


def daily_returns(series: Sequence[NavPoint]) -> list[float]:
    """One-session returns; a return across a gap in the history is left out."""
    return [
        current.nav / previous.nav - 1
        for previous, current in zip(series, series[1:])
        if skipped_weekdays(previous.report_date, current.report_date) <= MAX_SKIPPED_WEEKDAYS
    ]


def realised_volatility(returns: Sequence[float], window: int) -> AnalysisRealisedValue:
    """Annualised sample volatility of the latest `window` daily returns, in percent."""
    if len(returns) < window:
        return AnalysisRealisedValue(
            observations=len(returns),
            reason=f"Needs {window} daily NAV returns; {len(returns)} available.",
        )
    recent = returns[-window:]
    mean = sum(recent) / window
    variance = sum((value - mean) ** 2 for value in recent) / (window - 1)
    return AnalysisRealisedValue(
        value=math.sqrt(variance * TRADING_DAYS_PER_YEAR) * 100,
        observations=window,
    )


def drawdowns(series: Sequence[NavPoint]) -> tuple[AnalysisRealisedValue, AnalysisRealisedValue]:
    """Maximum and current drawdown from the running peak, as negative percents."""
    if len(series) < 2:
        missing = AnalysisRealisedValue(
            observations=len(series),
            reason="Needs at least 2 daily NAVs.",
        )
        return missing, missing
    peak = series[0].nav
    maximum = 0.0
    for point in series:
        peak = max(peak, point.nav)
        maximum = min(maximum, point.nav / peak - 1)
    current = series[-1].nav / peak - 1
    return (
        AnalysisRealisedValue(value=maximum * 100, observations=len(series)),
        AnalysisRealisedValue(value=current * 100, observations=len(series)),
    )


def realised_beta(
    series: Sequence[NavPoint],
    benchmark_bars: Sequence[CompletedDailyBar] | None,
) -> AnalysisRealisedValue:
    """Beta of NAV returns to SPY over their common dates (latest 252 returns)."""
    if not benchmark_bars:
        return AnalysisRealisedValue(reason="SPY daily bars are not available yet.")
    estimate = regress_beta(
        {point.report_date.isoformat(): point.nav for point in series},
        closes_by_date(benchmark_bars),
    )
    if estimate.beta is None:
        return AnalysisRealisedValue(
            observations=estimate.observations,
            reason=(
                f"Needs {MIN_BETA_OBSERVATIONS} daily NAV returns matched with SPY; "
                f"{estimate.observations} available."
            ),
        )
    return AnalysisRealisedValue(value=estimate.beta, observations=estimate.observations)


def build_realised_stats(
    points: Iterable[NavPoint],
    benchmark_bars: Sequence[CompletedDailyBar] | None,
) -> AnalysisRealisedStats:
    series = nav_series(points)
    returns = daily_returns(series)
    max_drawdown, current_drawdown = drawdowns(series)
    return AnalysisRealisedStats(
        currency=series[-1].currency if series else None,
        start_date=series[0].report_date if series else None,
        end_date=series[-1].report_date if series else None,
        nav_observations=len(series),
        volatility_20d_percent=realised_volatility(returns, VOLATILITY_WINDOWS[0]),
        volatility_60d_percent=realised_volatility(returns, VOLATILITY_WINDOWS[1]),
        max_drawdown_percent=max_drawdown,
        current_drawdown_percent=current_drawdown,
        beta=realised_beta(series, benchmark_bars),
    )
