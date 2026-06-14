from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Event, Lock
from time import monotonic, perf_counter
from typing import Protocol
from zoneinfo import ZoneInfo

from app.options.indicators import (
    calculate_bollinger_bands,
    calculate_rsi,
    latest_bollinger_band,
    latest_rsi,
    rsi_state_from_bars,
)
from app.options.domain import (
    OptionMetadata,
    bounded_strikes,
    chunk_date_range,
    days_to_expiration,
    missing_completed_ranges,
    option_chain_rows,
    same_month_day_years_ago,
    sorted_expirations,
    to_daily_closes,
    to_option_daily_bar,
)
from app.options.store import CompletedDailyBar, OptionsDailyBarStore
from app.tickers import normalize_ticker
from app.schemas import (
    BollingerBandPoint,
    OptionChainResponse,
    OptionChainLiveMessage,
    OptionExpiration,
    OptionExpirationsResponse,
    OptionQuote,
    OptionsAnalysisResponse,
    OptionsChartLiveMessage,
    RsiPoint,
)


logger = logging.getLogger(__name__)


class HistoricalDailyBarProvider(Protocol):
    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[CompletedDailyBar]:
        ...


class HistoricalDailyBarStreamProvider(Protocol):
    def stream_daily_bar_updates(
        self,
        ticker: str,
        stop_event: Event,
    ) -> Iterable[CompletedDailyBar]:
        ...


class OptionMetadataProvider(Protocol):
    def fetch_expirations(self, ticker: str) -> list[str]:
        ...

    def fetch_option_metadata(self, ticker: str) -> OptionMetadata:
        ...


OPTION_METADATA_CACHE_TTL_SECONDS = 15 * 60
ANALYSIS_UNDERLYING_PRICE_CACHE_TTL_SECONDS = 60
UNDERLYING_PRICE_LOOKBACK_DAYS = 7
US_MARKET_TIME_ZONE = ZoneInfo("America/New_York")


def current_us_market_date() -> date:
    return datetime.now(US_MARKET_TIME_ZONE).date()


@dataclass(frozen=True)
class CachedOptionMetadata:
    metadata: OptionMetadata
    expires_at: float


class CachedOptionMetadataProvider:
    def __init__(
        self,
        provider: OptionMetadataProvider,
        *,
        ttl_seconds: float = OPTION_METADATA_CACHE_TTL_SECONDS,
        current_time: Callable[[], float] = monotonic,
    ) -> None:
        self.provider = provider
        self.ttl_seconds = ttl_seconds
        self.current_time = current_time
        self.entries: dict[str, CachedOptionMetadata] = {}
        self.lock = Lock()

    def fetch_expirations(self, ticker: str) -> list[str]:
        return self.fetch_option_metadata(ticker).expirations

    def fetch_option_metadata(self, ticker: str) -> OptionMetadata:
        normalized_ticker = normalize_ticker(ticker)

        with self.lock:
            current_time = self.current_time()
            entry = self.entries.get(normalized_ticker)
            if entry is None or current_time >= entry.expires_at:
                metadata = self.provider.fetch_option_metadata(normalized_ticker)
                entry = CachedOptionMetadata(
                    metadata=copy_option_metadata(metadata),
                    expires_at=current_time + self.ttl_seconds,
                )
                self.entries[normalized_ticker] = entry

            return copy_option_metadata(entry.metadata)


def copy_option_metadata(metadata: OptionMetadata) -> OptionMetadata:
    return OptionMetadata(
        expirations=list(metadata.expirations),
        strikes=list(metadata.strikes),
    )


@dataclass(frozen=True)
class CachedUnderlyingPrice:
    price: float
    expires_at: float


class AnalysisUnderlyingPriceCache:
    def __init__(
        self,
        *,
        ttl_seconds: float = ANALYSIS_UNDERLYING_PRICE_CACHE_TTL_SECONDS,
        current_time: Callable[[], float] = monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.current_time = current_time
        self.entries: dict[str, CachedUnderlyingPrice] = {}
        self.lock = Lock()

    def get(self, ticker: str) -> float | None:
        normalized_ticker = normalize_ticker(ticker)

        with self.lock:
            entry = self.entries.get(normalized_ticker)
            if entry is None:
                return None
            if self.current_time() >= entry.expires_at:
                self.entries.pop(normalized_ticker, None)
                return None
            return entry.price

    def set(self, ticker: str, price: float) -> None:
        normalized_ticker = normalize_ticker(ticker)

        with self.lock:
            self.entries[normalized_ticker] = CachedUnderlyingPrice(
                price=price,
                expires_at=self.current_time() + self.ttl_seconds,
            )


class OptionChainSnapshotProvider(Protocol):
    def fetch_chain_quotes(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> dict[tuple[float, str], OptionQuote]:
        ...


class OptionChainStreamProvider(Protocol):
    def stream_chain_quotes(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: Event,
    ) -> Iterable[tuple[tuple[float, str], OptionQuote]]:
        ...


@dataclass(frozen=True)
class DailyBarsResult:
    ticker: str
    completed_bars: list[StoredDailyBar]
    current_bar: CompletedDailyBar | None = None
    metrics: DailyBarsMetrics | None = None


@dataclass(frozen=True)
class DailyBarsMetrics:
    cache_state: str
    history_chunk_count: int
    ib_wait_ms: float
    cache_hit_ratio: float
    payload_bytes: int


@dataclass(frozen=True)
class OptionChainContext:
    ticker: str
    expiration: str
    underlying_price: float | None
    strikes: list[float]


class OptionsClient:
    def __init__(
        self,
        store: OptionsDailyBarStore,
        historical_provider: HistoricalDailyBarProvider,
        metadata_provider: OptionMetadataProvider,
        chain_provider: OptionChainSnapshotProvider,
        chain_stream_provider: OptionChainStreamProvider,
        historical_stream_provider: HistoricalDailyBarStreamProvider,
        current_date_provider: Callable[[], date] = current_us_market_date,
        chain_context_workers: int = 2,
        max_chain_stream_strikes: int = 80,
    ) -> None:
        self.store = store
        self.historical_provider = historical_provider
        self.metadata_provider = CachedOptionMetadataProvider(metadata_provider)
        self.analysis_underlying_price_cache = AnalysisUnderlyingPriceCache()
        self.chain_provider = chain_provider
        self.chain_stream_provider = chain_stream_provider
        self.historical_stream_provider = historical_stream_provider
        self.current_date_provider = current_date_provider
        self.max_chain_stream_strikes = max(1, max_chain_stream_strikes)
        self.chain_context_executor = ThreadPoolExecutor(
            max_workers=max(1, chain_context_workers),
            thread_name_prefix="option-chain-context",
        )

    def shutdown(self) -> None:
        self.chain_context_executor.shutdown(wait=False, cancel_futures=True)

    def get_analysis(
        self,
        ticker: str,
        *,
        current_date: date | None = None,
    ) -> OptionsAnalysisResponse:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise OptionsDataUnavailable("Ticker is required.")

        daily_bars = self.load_daily_bars(
            normalized_ticker,
            current_date=current_date,
        )
        chart_bars = [
            *daily_bars.completed_bars,
            *([daily_bars.current_bar] if daily_bars.current_bar else []),
        ]
        if not chart_bars:
            raise OptionsDataUnavailable(
                f"No daily price data is available for {normalized_ticker}."
            )

        underlying_price = chart_bars[-1].close if chart_bars else None
        if underlying_price is not None:
            self.analysis_underlying_price_cache.set(
                normalized_ticker,
                underlying_price,
            )

        return OptionsAnalysisResponse(
            ticker=normalized_ticker,
            underlying_price=underlying_price,
            candles=[to_option_daily_bar(bar) for bar in chart_bars],
            bollinger_bands=[
                BollingerBandPoint(
                    date=value.date,
                    upper=value.upper,
                    middle=value.middle,
                    lower=value.lower,
                )
                for value in calculate_bollinger_bands(to_daily_closes(chart_bars))
            ],
            rsi=[
                RsiPoint(date=value.date, value=value.value)
                for value in calculate_rsi(to_daily_closes(chart_bars))
            ],
            message=f"Loaded analysis data for {normalized_ticker}.",
        )

    def get_underlying_price(
        self,
        ticker: str,
        *,
        current_date: date | None = None,
    ) -> float:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise OptionsDataUnavailable("Ticker is required.")

        as_of_date = current_date or self.current_date_provider()
        bars = self.historical_provider.fetch_daily_bars(
            normalized_ticker,
            as_of_date - timedelta(days=UNDERLYING_PRICE_LOOKBACK_DAYS),
            as_of_date,
        )
        latest_bar = max(bars, key=lambda bar: bar.trading_date, default=None)
        if latest_bar is None:
            raise OptionsDataUnavailable(
                f"Current price is unavailable for {normalized_ticker}."
            )

        return latest_bar.close

    def get_expirations(
        self,
        ticker: str,
        *,
        current_date: date | None = None,
    ) -> OptionExpirationsResponse:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise OptionsDataUnavailable("Ticker is required.")

        expirations = sorted_expirations(
            self.metadata_provider.fetch_expirations(normalized_ticker)
        )

        return OptionExpirationsResponse(
            ticker=normalized_ticker,
            expirations=[
                OptionExpiration(
                    date=expiration,
                    days_to_expiration=days_to_expiration(expiration, current_date),
                )
                for expiration in expirations
            ],
            selected_expiration=expirations[0] if expirations else None,
            message=f"Loaded expirations for {normalized_ticker}.",
        )

    def get_chain(
        self,
        ticker: str,
        expiration: str,
        *,
        current_date: date | None = None,
    ) -> OptionChainResponse:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise OptionsDataUnavailable("Ticker is required.")
        if not expiration:
            raise OptionsDataUnavailable("Expiration is required.")

        context = self.chain_context(
            normalized_ticker,
            expiration,
            current_date=current_date,
        )
        quotes = self.chain_provider.fetch_chain_quotes(
            context.ticker,
            context.expiration,
            context.strikes,
        )

        return OptionChainResponse(
            ticker=context.ticker,
            expiration=context.expiration,
            underlying_price=context.underlying_price,
            rows=option_chain_rows(context.strikes, quotes),
            message=(
                f"Loaded {len(context.strikes)} strike(s) for "
                f"{context.ticker} {context.expiration}."
            ),
        )

    def stream_chain(
        self,
        ticker: str,
        expiration: str,
        *,
        stop_event: Event,
        current_date: date | None = None,
    ) -> Iterable[OptionChainLiveMessage]:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise OptionsDataUnavailable("Ticker is required.")
        if not expiration:
            raise OptionsDataUnavailable("Expiration is required.")

        context = self.chain_context(
            normalized_ticker,
            expiration,
            current_date=current_date,
        )
        stream_strikes = context.strikes[: self.max_chain_stream_strikes]
        if len(stream_strikes) < len(context.strikes):
            logger.info(
                "Options chain stream strikes capped ticker=%s expiration=%s "
                "requested_strikes=%s streamed_strikes=%s",
                context.ticker,
                context.expiration,
                len(context.strikes),
                len(stream_strikes),
            )
        quotes: dict[tuple[float, str], OptionQuote] = {}

        yield OptionChainLiveMessage(
            type="snapshot",
            ticker=context.ticker,
            expiration=context.expiration,
            rows=option_chain_rows(stream_strikes, quotes),
            message=(
                f"Streaming {len(stream_strikes)} strike(s) for "
                f"{context.ticker} {context.expiration}."
            ),
        )

        for key, quote in self.chain_stream_provider.stream_chain_quotes(
            context.ticker,
            context.expiration,
            stream_strikes,
            stop_event,
        ):
            if stop_event.is_set():
                break

            quotes[key] = quote
            yield OptionChainLiveMessage(
                type="update",
                ticker=context.ticker,
                expiration=context.expiration,
                row=option_chain_rows([key[0]], quotes)[0],
            )

    def stream_chart(
        self,
        ticker: str,
        *,
        stop_event: Event,
        current_date: date | None = None,
    ) -> Iterable[OptionsChartLiveMessage]:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise OptionsDataUnavailable("Ticker is required.")

        active_bar: CompletedDailyBar | None = None
        completed_bars: list[StoredDailyBar] | list[CompletedDailyBar] | None = None
        completed_closes = None
        rsi_state = None

        for bar in self.historical_stream_provider.stream_daily_bar_updates(
            normalized_ticker,
            stop_event,
        ):
            as_of_date = current_date or self.current_date_provider()
            if completed_bars is None:
                start_date = same_month_day_years_ago(as_of_date, 10)
                latest_completed_date = as_of_date - timedelta(days=1)
                completed_bars = self.store.get_completed_bars(
                    normalized_ticker,
                    start_date=start_date.isoformat(),
                    end_date=latest_completed_date.isoformat(),
                )
                completed_closes = to_daily_closes(completed_bars)
                rsi_state = rsi_state_from_bars(completed_closes)

            if active_bar is not None and active_bar.trading_date != bar.trading_date:
                self.store.upsert_completed_bars(
                    [active_bar],
                    current_date=as_of_date,
                )
                completed_bars = append_completed_bar(completed_bars, active_bar)
                completed_closes = to_daily_closes(completed_bars)
                rsi_state = rsi_state_from_bars(completed_closes)

            if bar.trading_date != as_of_date.isoformat():
                continue

            assert completed_closes is not None
            assert rsi_state is not None
            chart_closes = [*completed_closes, to_daily_closes([bar])[0]]
            active_bar = bar
            self.analysis_underlying_price_cache.set(normalized_ticker, bar.close)
            bollinger_band = latest_bollinger_band(chart_closes)
            rsi = latest_rsi(rsi_state, chart_closes[-1])

            yield OptionsChartLiveMessage(
                type="update",
                ticker=normalized_ticker,
                candle=to_option_daily_bar(bar),
                bollinger_band=BollingerBandPoint(
                    date=bollinger_band.date,
                    upper=bollinger_band.upper,
                    middle=bollinger_band.middle,
                    lower=bollinger_band.lower,
                ),
                rsi=RsiPoint(date=rsi.date, value=rsi.value),
            )

    def chain_context(
        self,
        ticker: str,
        expiration: str,
        *,
        current_date: date | None = None,
    ) -> OptionChainContext:
        underlying_price = self.analysis_underlying_price_cache.get(ticker)
        if underlying_price is None:
            daily_bars_future = self.chain_context_executor.submit(
                self.load_daily_bars,
                ticker,
                current_date=current_date,
            )
            metadata_future = self.chain_context_executor.submit(
                self.metadata_provider.fetch_option_metadata,
                ticker,
            )
            daily_bars = daily_bars_future.result()
            metadata = metadata_future.result()

            chart_bars = [
                *daily_bars.completed_bars,
                *([daily_bars.current_bar] if daily_bars.current_bar else []),
            ]
            underlying_price = chart_bars[-1].close if chart_bars else None
        else:
            metadata = self.metadata_provider.fetch_option_metadata(ticker)

        if underlying_price is None:
            raise OptionsDataUnavailable(
                f"Underlying price is unavailable for {ticker}."
            )

        return OptionChainContext(
            ticker=ticker,
            expiration=expiration,
            underlying_price=underlying_price,
            strikes=bounded_strikes(metadata.strikes, underlying_price),
        )

    def load_daily_bars(
        self,
        ticker: str,
        *,
        current_date: date | None = None,
        years: int = 10,
    ) -> DailyBarsResult:
        normalized_ticker = normalize_ticker(ticker)
        as_of_date = current_date or self.current_date_provider()
        start_date = same_month_day_years_ago(as_of_date, years)
        latest_completed_date = as_of_date - timedelta(days=1)

        cached_bars = self.store.get_completed_bars(
            normalized_ticker,
            start_date=start_date.isoformat(),
            end_date=latest_completed_date.isoformat(),
        )
        missing_ranges = missing_completed_ranges(
            cached_bars,
            start_date=start_date,
            latest_completed_date=latest_completed_date,
            current_date=as_of_date,
        )
        missing_chunks = [
            chunk
            for missing_start, missing_end in missing_ranges
            for chunk in chunk_date_range(missing_start, missing_end)
        ]
        ib_started_at = perf_counter()
        fetched_bars = [
            bar
            for chunk_start, chunk_end in missing_chunks
            for bar in self.historical_provider.fetch_daily_bars(
                normalized_ticker,
                chunk_start,
                chunk_end,
            )
        ]
        ib_wait_ms = elapsed_ms(ib_started_at)
        self.store.upsert_completed_bars(
            fetched_bars,
            current_date=as_of_date,
        )

        completed_bars = self.store.get_completed_bars(
            normalized_ticker,
            start_date=start_date.isoformat(),
            end_date=latest_completed_date.isoformat(),
        )
        current_bar = next(
            (
                bar
                for bar in fetched_bars
                if bar.trading_date == as_of_date.isoformat()
            ),
            None,
        )
        metrics = DailyBarsMetrics(
            cache_state="warm" if not missing_chunks else "cold",
            history_chunk_count=len(missing_chunks),
            ib_wait_ms=ib_wait_ms,
            cache_hit_ratio=cache_hit_ratio(
                len(cached_bars),
                start_date=start_date,
                latest_completed_date=latest_completed_date,
            ),
            payload_bytes=completed_bar_payload_bytes(fetched_bars),
        )
        logger.info(
            "Options historical hydration ticker=%s cache_state=%s chunks=%s "
            "ib_wait_ms=%.1f cache_hit_ratio=%.3f payload_bytes=%s",
            normalized_ticker,
            metrics.cache_state,
            metrics.history_chunk_count,
            metrics.ib_wait_ms,
            metrics.cache_hit_ratio,
            metrics.payload_bytes,
        )

        return DailyBarsResult(
            ticker=normalized_ticker,
            completed_bars=completed_bars,
            current_bar=current_bar,
            metrics=metrics,
        )


class UnavailableOptionMetadataProvider:
    def fetch_expirations(self, ticker: str) -> list[str]:
        raise OptionsDataUnavailable(
            "Options metadata provider is not configured."
        )

    def fetch_option_metadata(self, ticker: str) -> OptionMetadata:
        raise OptionsDataUnavailable(
            "Options metadata provider is not configured."
        )


class UnavailableHistoricalDailyBarStreamProvider:
    def stream_daily_bar_updates(
        self,
        ticker: str,
        stop_event: Event,
    ) -> Iterable[CompletedDailyBar]:
        raise OptionsDataUnavailable(
            "Options chart stream provider is not configured."
        )


class UnavailableOptionChainSnapshotProvider:
    def fetch_chain_quotes(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> dict[tuple[float, str], OptionQuote]:
        raise OptionsDataUnavailable(
            "Options chain provider is not configured."
        )


class UnavailableOptionChainStreamProvider:
    def stream_chain_quotes(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: Event,
    ) -> Iterable[tuple[tuple[float, str], OptionQuote]]:
        raise OptionsDataUnavailable(
            "Options chain stream provider is not configured."
        )


def fetch_chunked_daily_bars(
    provider: HistoricalDailyBarProvider,
    ticker: str,
    ranges: Iterable[tuple[date, date]],
) -> Iterable[CompletedDailyBar]:
    for start_date, end_date in ranges:
        for chunk_start, chunk_end in chunk_date_range(start_date, end_date):
            yield from provider.fetch_daily_bars(ticker, chunk_start, chunk_end)


class OptionsDataUnavailable(Exception):
    pass


def cache_hit_ratio(
    cached_bar_count: int,
    *,
    start_date: date,
    latest_completed_date: date,
) -> float:
    expected_days = max(1, (latest_completed_date - start_date).days + 1)
    return min(1, cached_bar_count / expected_days)


def completed_bar_payload_bytes(bars: list[CompletedDailyBar]) -> int:
    return len(
        json.dumps(
            [
                {
                    "ticker": bar.ticker,
                    "trading_date": bar.trading_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars
            ],
            separators=(",", ":"),
        )
    )


def elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1_000


def append_completed_bar(
    bars: list[StoredDailyBar],
    bar: CompletedDailyBar,
) -> list[CompletedDailyBar]:
    return [
        *[current_bar for current_bar in bars if current_bar.trading_date != bar.trading_date],
        bar,
    ]
