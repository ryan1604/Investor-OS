from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Event, Lock
from time import monotonic
from typing import Protocol
from zoneinfo import ZoneInfo

from app.options.indicators import (
    calculate_bollinger_bands,
    calculate_rsi,
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
from app.options.store import (
    CompletedDailyBar,
    OptionsDailyBarStore,
    normalize_ticker,
)
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
    ) -> None:
        self.store = store
        self.historical_provider = historical_provider
        self.metadata_provider = CachedOptionMetadataProvider(metadata_provider)
        self.analysis_underlying_price_cache = AnalysisUnderlyingPriceCache()
        self.chain_provider = chain_provider
        self.chain_stream_provider = chain_stream_provider
        self.historical_stream_provider = historical_stream_provider
        self.current_date_provider = current_date_provider

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
        quotes: dict[tuple[float, str], OptionQuote] = {}

        yield OptionChainLiveMessage(
            type="snapshot",
            ticker=context.ticker,
            expiration=context.expiration,
            rows=option_chain_rows(context.strikes, quotes),
            message=(
                f"Streaming {len(context.strikes)} strike(s) for "
                f"{context.ticker} {context.expiration}."
            ),
        )

        for key, quote in self.chain_stream_provider.stream_chain_quotes(
            context.ticker,
            context.expiration,
            context.strikes,
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

        for bar in self.historical_stream_provider.stream_daily_bar_updates(
            normalized_ticker,
            stop_event,
        ):
            as_of_date = current_date or self.current_date_provider()
            start_date = same_month_day_years_ago(as_of_date, 10)
            latest_completed_date = as_of_date - timedelta(days=1)
            if active_bar is not None:
                self.store.upsert_completed_bars(
                    [active_bar],
                    current_date=as_of_date,
                )
            self.store.upsert_completed_bars([bar], current_date=as_of_date)
            completed_bars = self.store.get_completed_bars(
                normalized_ticker,
                start_date=start_date.isoformat(),
                end_date=latest_completed_date.isoformat(),
            )
            chart_bars = [
                *completed_bars,
                *([bar] if bar.trading_date == as_of_date.isoformat() else []),
            ]
            if (
                bar.trading_date != as_of_date.isoformat()
                or not chart_bars
                or chart_bars[-1].trading_date != bar.trading_date
            ):
                continue

            active_bar = (
                bar if bar.trading_date == as_of_date.isoformat() else None
            )
            self.analysis_underlying_price_cache.set(normalized_ticker, bar.close)
            bollinger_band = calculate_bollinger_bands(
                to_daily_closes(chart_bars)
            )[-1]
            rsi = calculate_rsi(to_daily_closes(chart_bars))[-1]

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
            with ThreadPoolExecutor(max_workers=2) as executor:
                daily_bars_future = executor.submit(
                    self.load_daily_bars,
                    ticker,
                    current_date=current_date,
                )
                metadata_future = executor.submit(
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
        fetched_bars = list(
            fetch_chunked_daily_bars(
                self.historical_provider,
                normalized_ticker,
                missing_ranges,
            )
        )
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

        return DailyBarsResult(
            ticker=normalized_ticker,
            completed_bars=completed_bars,
            current_bar=current_bar,
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
