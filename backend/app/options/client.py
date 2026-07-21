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
    option_chain_has_delta_window,
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
OPTION_CHAIN_CONTRACT_CACHE_TTL_SECONDS = 15 * 60
OPTION_CHAIN_QUOTE_CACHE_TTL_SECONDS = 5
OPTION_CHAIN_PREFETCH_EXPIRATION_COUNT = 3
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


@dataclass(frozen=True)
class CachedOptionChainContracts:
    contracts: list[ScannerOptionContract]
    expires_at: float


@dataclass(frozen=True)
class CachedOptionChainQuote:
    quote: OptionQuote
    cached_at: float
    expires_at: float


@dataclass
class OptionChainContractsInFlight:
    ready: Event
    contracts: list[ScannerOptionContract] | None = None
    error: BaseException | None = None


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
    def fetch_chain_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> list[ScannerOptionContract]:
        ...

    def fetch_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
    ) -> dict[tuple[float, str], OptionQuote]:
        ...


class OptionChainStreamProvider(Protocol):
    def stream_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
        stop_event: Event,
    ) -> Iterable[tuple[tuple[float, str], OptionQuote]]:
        ...


@dataclass(frozen=True)
class ScannerOptionContract:
    con_id: int
    ticker: str
    expiration: str
    strike: float
    right: str
    exchange: str
    currency: str
    multiplier: str
    trading_class: str
    local_symbol: str


@dataclass(frozen=True)
class ScannerOptionQuote:
    contract: ScannerOptionContract
    bid: float | None
    ask: float | None
    delta: float | None


@dataclass(frozen=True)
class ScannerContractSelection:
    contracts: list[ScannerOptionContract]
    excluded_contracts: int = 0


class OptionScannerProvider(Protocol):
    def fetch_option_contracts(
        self,
        ticker: str,
        expirations: list[str],
        strikes: list[float],
        right: str,
        cancel_event: Event,
    ) -> ScannerContractSelection:
        ...

    def fetch_quotes(
        self,
        contracts: list[ScannerOptionContract],
        cancel_event: Event,
    ) -> list[ScannerOptionQuote]:
        ...

    def refresh_quote(
        self,
        *,
        ticker: str,
        expiration: str,
        strike: float,
        right: str,
        con_id: int | None,
        local_symbol: str | None,
    ) -> ScannerOptionQuote:
        ...

    def cancel(self) -> None:
        ...


@dataclass(frozen=True)
class FullOptionChainSnapshot:
    ticker: str
    underlying_price: float
    underlying_price_captured_at: datetime
    contracts: list[ScannerOptionQuote]
    excluded_contracts: int = 0


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
    contracts: list[ScannerOptionContract]


class OptionsClient:
    def __init__(
        self,
        store: OptionsDailyBarStore,
        historical_provider: HistoricalDailyBarProvider,
        metadata_provider: OptionMetadataProvider,
        chain_provider: OptionChainSnapshotProvider,
        chain_stream_provider: OptionChainStreamProvider,
        historical_stream_provider: HistoricalDailyBarStreamProvider,
        scanner_provider: OptionScannerProvider | None = None,
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
        self.scanner_provider = scanner_provider
        self.current_date_provider = current_date_provider
        self.max_chain_stream_strikes = max(1, max_chain_stream_strikes)
        self.contract_cache_ttl_seconds = OPTION_CHAIN_CONTRACT_CACHE_TTL_SECONDS
        self.contract_cache: dict[
            tuple[str, str, tuple[float, ...]],
            CachedOptionChainContracts,
        ] = {}
        self.contract_cache_in_flight: dict[
            tuple[str, str, tuple[float, ...]],
            OptionChainContractsInFlight,
        ] = {}
        self.contract_cache_lock = Lock()
        self.quote_cache_ttl_seconds = OPTION_CHAIN_QUOTE_CACHE_TTL_SECONDS
        self.quote_cache: dict[
            tuple[str, str, float, str, int],
            CachedOptionChainQuote,
        ] = {}
        self.quote_cache_lock = Lock()
        self.chain_prefetch_generation = 0
        self.chain_prefetch_lock = Lock()
        self.chain_prefetch_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="option-chain-prefetch",
        )
        self.chain_context_executor = ThreadPoolExecutor(
            max_workers=max(1, chain_context_workers),
            thread_name_prefix="option-chain-context",
        )

    def shutdown(self) -> None:
        if self.scanner_provider is not None:
            self.scanner_provider.cancel()
        self.chain_prefetch_executor.shutdown(wait=False, cancel_futures=True)
        self.chain_context_executor.shutdown(wait=False, cancel_futures=True)

    def get_full_option_chain(
        self,
        ticker: str,
        *,
        right: str,
        minimum_dte: int,
        maximum_dte: int,
        cancel_event: Event,
        current_date: date | None = None,
    ) -> FullOptionChainSnapshot:
        if self.scanner_provider is None:
            raise OptionsDataUnavailable(
                "Options scanner provider is not configured."
            )

        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise OptionsDataUnavailable("Ticker is required.")

        as_of_date = current_date or self.current_date_provider()
        underlying_price = self.get_underlying_price(
            normalized_ticker,
            current_date=as_of_date,
        )
        captured_at = datetime.now(US_MARKET_TIME_ZONE)
        metadata = self.metadata_provider.fetch_option_metadata(normalized_ticker)
        expirations = [
            expiration
            for expiration in sorted_expirations(metadata.expirations)
            if minimum_dte
            <= days_to_expiration(expiration, as_of_date)
            <= maximum_dte
        ]
        strikes = [
            strike
            for strike in metadata.strikes
            if (
                strike < underlying_price
                if right == "P"
                else strike > underlying_price
            )
        ]
        selection = self.scanner_provider.fetch_option_contracts(
            normalized_ticker,
            expirations,
            strikes,
            right,
            cancel_event,
        )
        quotes = self.scanner_provider.fetch_quotes(
            selection.contracts,
            cancel_event,
        )
        return FullOptionChainSnapshot(
            ticker=normalized_ticker,
            underlying_price=underlying_price,
            underlying_price_captured_at=captured_at,
            contracts=quotes,
            excluded_contracts=selection.excluded_contracts,
        )

    def cancel_scanner(self) -> None:
        if self.scanner_provider is not None:
            self.scanner_provider.cancel()

    def refresh_option_quote(
        self,
        *,
        ticker: str,
        expiration: str,
        strike: float,
        right: str,
        con_id: int | None,
        local_symbol: str | None,
    ) -> ScannerOptionQuote:
        if self.scanner_provider is None:
            raise OptionsDataUnavailable(
                "Options scanner provider is not configured."
            )

        return self.scanner_provider.refresh_quote(
            ticker=normalize_ticker(ticker),
            expiration=expiration,
            strike=strike,
            right=right,
            con_id=con_id,
            local_symbol=local_symbol,
        )

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

        metadata = self.metadata_provider.fetch_option_metadata(normalized_ticker)
        expirations = sorted_expirations(metadata.expirations)
        self.prefetch_chain_contracts(normalized_ticker, metadata, expirations)

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

    def prefetch_chain_contracts(
        self,
        ticker: str,
        metadata: OptionMetadata,
        expirations: list[str],
    ) -> None:
        selected_expirations = expirations[:OPTION_CHAIN_PREFETCH_EXPIRATION_COUNT]
        underlying_price = self.analysis_underlying_price_cache.get(ticker)
        if underlying_price is None or not selected_expirations:
            logger.info(
                "Option chain prefetch skipped ticker=%s reason=%s",
                ticker,
                "missing_underlying_price"
                if underlying_price is None
                else "missing_expirations",
            )
            return

        strikes = bounded_strikes(metadata.strikes, underlying_price)
        if not strikes:
            logger.info(
                "Option chain prefetch skipped ticker=%s reason=missing_strikes",
                ticker,
            )
            return

        with self.chain_prefetch_lock:
            self.chain_prefetch_generation += 1
            generation = self.chain_prefetch_generation

        logger.info(
            "Option chain prefetch queued ticker=%s expirations=%s strikes=%s",
            ticker,
            len(selected_expirations),
            len(strikes),
        )
        self.chain_prefetch_executor.submit(
            self._prefetch_chain_contracts,
            ticker,
            selected_expirations,
            strikes,
            generation,
        )

    def _prefetch_chain_contracts(
        self,
        ticker: str,
        expirations: list[str],
        strikes: list[float],
        generation: int,
    ) -> None:
        for expiration in expirations:
            with self.chain_prefetch_lock:
                if generation != self.chain_prefetch_generation:
                    logger.info(
                        "Option chain prefetch cancelled ticker=%s expiration=%s",
                        ticker,
                        expiration,
                    )
                    return

            started_at = perf_counter()
            try:
                contracts = self.chain_contracts(
                    ticker,
                    expiration,
                    strikes,
                    cacheable=True,
                )
            except Exception:
                logger.exception(
                    "Option chain prefetch failed ticker=%s expiration=%s",
                    ticker,
                    expiration,
                )
                continue

            logger.info(
                "Option chain prefetch complete ticker=%s expiration=%s "
                "contracts=%s elapsed_ms=%.1f",
                ticker,
                expiration,
                len(contracts),
                elapsed_ms(started_at),
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
        quotes = self.chain_provider.fetch_chain_quotes(context.contracts)
        self.remember_chain_quotes(context.contracts, quotes)

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
        stream_strikes = capped_chain_strikes(
            context.strikes,
            context.underlying_price,
            self.max_chain_stream_strikes,
        )
        stream_strike_set = set(stream_strikes)
        stream_contracts = [
            contract
            for contract in context.contracts
            if contract.strike in stream_strike_set
        ]
        if len(stream_strikes) < len(context.strikes):
            logger.info(
                "Options chain stream strikes capped ticker=%s expiration=%s "
                "requested_strikes=%s streamed_strikes=%s",
                context.ticker,
                context.expiration,
                len(context.strikes),
                len(stream_strikes),
            )
        quotes = self.cached_chain_quotes(stream_contracts)
        has_delta_window = option_chain_has_delta_window(stream_strikes, quotes)

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
            stream_contracts,
            stop_event,
        ):
            if stop_event.is_set():
                break

            quotes[key] = quote
            self.remember_chain_quotes(stream_contracts, {key: quote})
            rows = option_chain_rows(stream_strikes, quotes)
            next_has_delta_window = option_chain_has_delta_window(
                stream_strikes,
                quotes,
            )
            if next_has_delta_window and not has_delta_window:
                has_delta_window = True
                yield OptionChainLiveMessage(
                    type="snapshot",
                    ticker=context.ticker,
                    expiration=context.expiration,
                    rows=rows,
                    message=(
                        f"Streaming {len(stream_strikes)} strike(s) for "
                        f"{context.ticker} {context.expiration}."
                    ),
                )
                continue
            row = next(
                (
                    row
                    for row in rows
                    if row.strike == key[0]
                ),
                None,
            )
            if row is None:
                continue
            yield OptionChainLiveMessage(
                type="update",
                ticker=context.ticker,
                expiration=context.expiration,
                row=row,
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

        strikes = bounded_strikes(metadata.strikes, underlying_price)
        contracts = self.chain_contracts(
            ticker,
            expiration,
            strikes,
            cacheable=not metadata.expirations or expiration in metadata.expirations,
        )
        contract_strikes = sorted({contract.strike for contract in contracts})

        return OptionChainContext(
            ticker=ticker,
            expiration=expiration,
            underlying_price=underlying_price,
            strikes=contract_strikes,
            contracts=contracts,
        )

    def chain_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        *,
        cacheable: bool,
    ) -> list[ScannerOptionContract]:
        if not cacheable:
            self.clear_contract_cache(ticker, expiration)
            return self.chain_provider.fetch_chain_contracts(ticker, expiration, strikes)

        key = (ticker, expiration, tuple(strikes))
        current_time = monotonic()
        with self.contract_cache_lock:
            entry = self.contract_cache.get(key)
            if entry is not None and current_time < entry.expires_at:
                logger.info(
                    "Option chain contract cache hit ticker=%s expiration=%s "
                    "strikes=%s contracts=%s",
                    ticker,
                    expiration,
                    len(strikes),
                    len(entry.contracts),
                )
                return list(entry.contracts)
            if entry is not None:
                self.contract_cache.pop(key, None)

            in_flight = self.contract_cache_in_flight.get(key)
            if in_flight is None:
                in_flight = OptionChainContractsInFlight(ready=Event())
                self.contract_cache_in_flight[key] = in_flight
                owner = True
                logger.info(
                    "Option chain contract cache miss ticker=%s expiration=%s "
                    "strikes=%s",
                    ticker,
                    expiration,
                    len(strikes),
                )
            else:
                owner = False
                logger.info(
                    "Option chain contract cache sharing in-flight hydration "
                    "ticker=%s expiration=%s strikes=%s",
                    ticker,
                    expiration,
                    len(strikes),
                )

        if not owner:
            in_flight.ready.wait()
            if in_flight.error is not None:
                raise in_flight.error
            return list(in_flight.contracts or [])

        started_at = perf_counter()
        try:
            contracts = self.chain_provider.fetch_chain_contracts(
                ticker,
                expiration,
                strikes,
            )
        except BaseException as error:
            with self.contract_cache_lock:
                in_flight.error = error
                self.contract_cache_in_flight.pop(key, None)
                in_flight.ready.set()
            raise

        with self.contract_cache_lock:
            in_flight.contracts = contracts
            self.contract_cache[key] = CachedOptionChainContracts(
                contracts=list(contracts),
                expires_at=monotonic() + self.contract_cache_ttl_seconds,
            )
            self.contract_cache_in_flight.pop(key, None)
            in_flight.ready.set()

        logger.info(
            "Option chain contract hydration complete ticker=%s expiration=%s "
            "strikes=%s contracts=%s ib_wait_ms=%.1f",
            ticker,
            expiration,
            len(strikes),
            len(contracts),
            elapsed_ms(started_at),
        )
        return list(contracts)

    def clear_contract_cache(self, ticker: str, expiration: str) -> None:
        with self.contract_cache_lock:
            for key in list(self.contract_cache):
                if key[0] == ticker and key[1] == expiration:
                    self.contract_cache.pop(key, None)

    def cached_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
    ) -> dict[tuple[float, str], OptionQuote]:
        current_time = monotonic()
        quotes: dict[tuple[float, str], OptionQuote] = {}
        expired_keys = []
        newest_cached_at: float | None = None

        with self.quote_cache_lock:
            for contract in contracts:
                key = option_quote_cache_key(contract)
                entry = self.quote_cache.get(key)
                if entry is None:
                    continue
                if current_time >= entry.expires_at:
                    expired_keys.append(key)
                    continue

                newest_cached_at = max(
                    newest_cached_at or entry.cached_at,
                    entry.cached_at,
                )
                quotes[(contract.strike, contract.right)] = entry.quote.model_copy(
                    deep=True,
                )

            for key in expired_keys:
                self.quote_cache.pop(key, None)

        age_ms = (
            (current_time - newest_cached_at) * 1_000
            if newest_cached_at is not None
            else None
        )
        logger.info(
            "Option chain quote cache ticker=%s expiration=%s hits=%s misses=%s "
            "expired=%s newest_age_ms=%s",
            contracts[0].ticker if contracts else "",
            contracts[0].expiration if contracts else "",
            len(quotes),
            max(0, len(contracts) - len(quotes) - len(expired_keys)),
            len(expired_keys),
            f"{age_ms:.1f}" if age_ms is not None else None,
        )
        return quotes

    def remember_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
        quotes: dict[tuple[float, str], OptionQuote],
    ) -> None:
        contracts_by_quote_key = {
            (contract.strike, contract.right): contract
            for contract in contracts
        }
        current_time = monotonic()

        with self.quote_cache_lock:
            for quote_key, quote in quotes.items():
                contract = contracts_by_quote_key.get(quote_key)
                if contract is None:
                    continue

                self.quote_cache[option_quote_cache_key(contract)] = (
                    CachedOptionChainQuote(
                        quote=quote.model_copy(deep=True),
                        cached_at=current_time,
                        expires_at=current_time + self.quote_cache_ttl_seconds,
                    )
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


def capped_chain_strikes(
    strikes: list[float],
    underlying_price: float | None,
    maximum_count: int,
) -> list[float]:
    if len(strikes) <= maximum_count or underlying_price is None:
        return strikes[:maximum_count]

    return sorted(
        sorted(strikes, key=lambda strike: (abs(strike - underlying_price), strike))[
            :maximum_count
        ]
    )


def option_quote_cache_key(
    contract: ScannerOptionContract,
) -> tuple[str, str, float, str, int]:
    return (
        contract.ticker,
        contract.expiration,
        contract.strike,
        contract.right,
        contract.con_id,
    )
