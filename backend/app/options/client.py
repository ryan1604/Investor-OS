from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Condition, Event, Lock
from time import monotonic, perf_counter

from app.ib.contracts import option_right_code
from app.options.indicators import (
    calculate_bollinger_bands,
    calculate_rsi,
    latest_bollinger_band,
    latest_rsi,
    rsi_state_from_bars,
)
from app.options.domain import (
    OptionMetadata,
    chunk_date_range,
    days_to_expiration,
    missing_completed_ranges,
    option_chain_delta_bounds,
    option_chain_rows,
    option_chain_strikes,
    same_month_day_years_ago,
    sorted_expirations,
    to_daily_closes,
    to_option_daily_bar,
    append_completed_bar,
    cache_hit_ratio,
    completed_bar_payload_bytes,
    current_us_market_date,
)
from app.options.rotation import (
    ChainStreamTiming,
    OPTION_RIGHT_CODES,
    OptionChainRotation,
    capped_chain_strikes,
    nearest_contracts_first,
    preferred_chain_contracts,
    preferred_chain_contracts_from_entries,
)
from app.options.types import (
    ContractLookupPriority,
    DailyBarsMetrics,
    DailyBarsResult,
    FullOptionChainSnapshot,
    HistoricalDailyBarProvider,
    HistoricalDailyBarStreamProvider,
    OptionChainContext,
    OptionChainContractHydration,
    OptionChainSnapshotProvider,
    OptionChainStreamNotice,
    OptionChainStreamProvider,
    OptionMetadataProvider,
    OptionScannerProvider,
    OptionsDataUnavailable,
    ScannerContractSelection,
    ScannerOptionContract,
    ScannerOptionQuote,
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
from app.sessions import US_MARKET_TIME_ZONE
from app.timing import elapsed_ms


logger = logging.getLogger(__name__)


OPTION_METADATA_CACHE_TTL_SECONDS = 15 * 60
ANALYSIS_UNDERLYING_PRICE_CACHE_TTL_SECONDS = 60
# Exact fallback resolves the displayed strikes plus this margin on each side.
OPTION_CHAIN_FALLBACK_STRIKE_MARGIN = 8
OPTION_CHAIN_QUOTE_CACHE_TTL_SECONDS = 5
OPTION_CHAIN_PREFETCH_EXPIRATION_COUNT = 3
OPTION_CHAIN_PREFETCH_PRICE_WAIT_SECONDS = 10
UNDERLYING_PRICE_LOOKBACK_DAYS = 7


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
        # One lock per ticker, so a slow fetch never holds up other tickers.
        self.ticker_locks: dict[str, Lock] = {}

    def fetch_option_metadata(self, ticker: str) -> OptionMetadata:
        normalized_ticker = normalize_ticker(ticker)

        with self.lock:
            ticker_lock = self.ticker_locks.setdefault(normalized_ticker, Lock())
        with ticker_lock:
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
class CachedOptionChainQuote:
    quote: OptionQuote
    cached_at: float
    expires_at: float


@dataclass
class OptionChainContractsInFlight:
    ready: Event
    priority: ContractLookupPriority
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
        self.condition = Condition()

    def get(self, ticker: str) -> float | None:
        with self.condition:
            return self._get(normalize_ticker(ticker))

    def wait(self, ticker: str, timeout: float) -> float | None:
        """Return the price once analysis caches it, or None after timeout."""
        normalized_ticker = normalize_ticker(ticker)
        with self.condition:
            self.condition.wait_for(
                lambda: self._get(normalized_ticker) is not None,
                timeout=max(0, timeout),
            )
            return self._get(normalized_ticker)

    def set(self, ticker: str, price: float) -> None:
        normalized_ticker = normalize_ticker(ticker)

        with self.condition:
            self.entries[normalized_ticker] = CachedUnderlyingPrice(
                price=price,
                expires_at=self.current_time() + self.ttl_seconds,
            )
            self.condition.notify_all()

    def _get(self, normalized_ticker: str) -> float | None:
        entry = self.entries.get(normalized_ticker)
        if entry is None:
            return None
        if self.current_time() >= entry.expires_at:
            self.entries.pop(normalized_ticker, None)
            return None
        return entry.price


class OptionContractCache:
    """Resolved option contracts per strike for the current US market date.

    An empty entry records a strike IB reported as nonexistent. Timeouts are
    never stored, so those strikes are requested again.
    """

    def __init__(
        self,
        current_date_provider: Callable[[], date] = current_us_market_date,
    ) -> None:
        self.current_date_provider = current_date_provider
        self.market_date: date | None = None
        self.entries: dict[
            tuple[str, str, str, float],
            tuple[ScannerOptionContract, ...],
        ] = {}
        self.skipped_strikes: dict[tuple[str, str], frozenset[float]] = {}
        self.lock = Lock()

    def get_many(
        self,
        ticker: str,
        right: str,
        lookups: Iterable[tuple[str, float]],
    ) -> dict[tuple[str, float], tuple[ScannerOptionContract, ...]]:
        with self.lock:
            self._roll_market_date()
            return {
                (expiration, strike): self.entries[key]
                for expiration, strike in lookups
                if (key := (ticker, expiration, right, strike)) in self.entries
            }

    def store(
        self,
        ticker: str,
        right: str,
        entries: dict[tuple[str, float], Iterable[ScannerOptionContract]],
    ) -> None:
        with self.lock:
            self._roll_market_date()
            for (expiration, strike), contracts in entries.items():
                self.entries[(ticker, expiration, right, strike)] = tuple(contracts)

    def chain_skipped_strikes(self, ticker: str, expiration: str) -> frozenset[float]:
        with self.lock:
            self._roll_market_date()
            return self.skipped_strikes.get((ticker, expiration), frozenset())

    def remember_chain_skipped_strikes(
        self,
        ticker: str,
        expiration: str,
        strikes: Iterable[float],
    ) -> None:
        with self.lock:
            self._roll_market_date()
            key = (ticker, expiration)
            self.skipped_strikes[key] = self.skipped_strikes.get(
                key,
                frozenset(),
            ).union(strikes)

    def clear(self, ticker: str, expiration: str) -> None:
        with self.lock:
            for key in [
                key
                for key in self.entries
                if key[0] == ticker and key[1] == expiration
            ]:
                self.entries.pop(key, None)
            self.skipped_strikes.pop((ticker, expiration), None)

    def _roll_market_date(self) -> None:
        market_date = self.current_date_provider()
        if market_date != self.market_date:
            self.entries.clear()
            self.skipped_strikes.clear()
            self.market_date = market_date


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
        max_chain_strikes: int = 80,
        contract_cache: OptionContractCache | None = None,
        *,
        max_chain_stream_strikes: int,
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
        self.max_chain_strikes = max(1, max_chain_strikes)
        self.max_chain_stream_strikes = max(1, max_chain_stream_strikes)
        self.chain_fallback_strike_count = (
            self.max_chain_strikes + 2 * OPTION_CHAIN_FALLBACK_STRIKE_MARGIN
        )
        self.contract_cache = contract_cache or OptionContractCache(
            current_date_provider
        )
        self.contract_cache_in_flight: dict[
            tuple[str, str],
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
        self.chain_prefetch_price_wait_seconds = OPTION_CHAIN_PREFETCH_PRICE_WAIT_SECONDS
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
        started_at = perf_counter()
        underlying_price = self.get_underlying_price(
            normalized_ticker,
            current_date=as_of_date,
        )
        price_ms = elapsed_ms(started_at)
        captured_at = datetime.now(US_MARKET_TIME_ZONE)
        metadata_started_at = perf_counter()
        metadata = self.metadata_provider.fetch_option_metadata(normalized_ticker)
        metadata_ms = elapsed_ms(metadata_started_at)
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
        contracts_started_at = perf_counter()
        selection = self.scanner_contracts(
            normalized_ticker,
            expirations,
            strikes,
            right,
            cancel_event,
        )
        contracts_ms = elapsed_ms(contracts_started_at)
        quotes_started_at = perf_counter()
        quotes = self.scanner_provider.fetch_quotes(
            selection.contracts,
            cancel_event,
        )
        logger.info(
            "Options scanner chain timing ticker=%s right=%s expirations=%s "
            "strikes=%s contracts=%s excluded_contracts=%s price_ms=%.1f "
            "metadata_ms=%.1f contracts_ms=%.1f quotes_ms=%.1f total_ms=%.1f",
            normalized_ticker,
            right,
            len(expirations),
            len(strikes),
            len(selection.contracts),
            selection.excluded_contracts,
            price_ms,
            metadata_ms,
            contracts_ms,
            elapsed_ms(quotes_started_at),
            elapsed_ms(started_at),
        )
        return FullOptionChainSnapshot(
            ticker=normalized_ticker,
            underlying_price=underlying_price,
            underlying_price_captured_at=captured_at,
            contracts=quotes,
            excluded_contracts=selection.excluded_contracts,
            line_limited_contracts=sum(1 for quote in quotes if quote.line_limited),
        )

    def scanner_contracts(
        self,
        ticker: str,
        expirations: list[str],
        strikes: list[float],
        right: str,
        cancel_event: Event,
    ) -> ScannerContractSelection:
        assert self.scanner_provider is not None
        lookups = [
            (expiration, strike)
            for expiration in expirations
            for strike in sorted(set(strikes))
        ]
        resolved = self.contract_cache.get_many(ticker, right, lookups)
        missing = [lookup for lookup in lookups if lookup not in resolved]
        if missing:
            selection = self.scanner_provider.fetch_option_contracts(
                ticker,
                missing,
                right,
                cancel_event,
            )
            fetched: dict[tuple[str, float], list[ScannerOptionContract]] = {
                lookup: [] for lookup in selection.invalid_lookups
            }
            for contract in selection.contracts:
                fetched.setdefault((contract.expiration, contract.strike), []).append(
                    contract
                )
            self.contract_cache.store(ticker, right, fetched)
            resolved = {**resolved, **{key: tuple(value) for key, value in fetched.items()}}
        logger.info(
            "Options scanner contract cache ticker=%s right=%s lookups=%s "
            "cached=%s requested=%s",
            ticker,
            right,
            len(lookups),
            len(lookups) - len(missing),
            len(missing),
        )
        contracts = [
            contract for lookup in lookups for contract in resolved.get(lookup, ())
        ]
        return ScannerContractSelection(
            contracts=contracts,
            excluded_contracts=sum(1 for lookup in lookups if not resolved.get(lookup)),
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
        if not selected_expirations:
            logger.info(
                "Option chain prefetch skipped ticker=%s reason=missing_expirations",
                ticker,
            )
            return

        strikes = option_chain_strikes(metadata.strikes)
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
        underlying_price = self.prefetch_underlying_price(ticker, generation)
        for expiration in expirations:
            if self.chain_prefetch_superseded(generation):
                logger.info(
                    "Option chain prefetch cancelled ticker=%s expiration=%s",
                    ticker,
                    expiration,
                )
                return

            started_at = perf_counter()
            try:
                # Without a price, exact fallback would look up every strike
                # and crowd out the chain the user opens.
                contracts = self.chain_contracts(
                    ticker,
                    expiration,
                    strikes,
                    cacheable=True,
                    underlying_price=underlying_price,
                    fallback_without_price=False,
                    background=True,
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

    def prefetch_underlying_price(self, ticker: str, generation: int) -> float | None:
        # Expirations are requested alongside analysis, which caches the price
        # that limits exact-lookup fallback to strikes near the money.
        deadline = monotonic() + self.chain_prefetch_price_wait_seconds
        while True:
            remaining = deadline - monotonic()
            underlying_price = self.analysis_underlying_price_cache.wait(
                ticker,
                min(0.25, remaining),
            )
            if (
                underlying_price is not None
                or remaining <= 0
                or self.chain_prefetch_superseded(generation)
            ):
                return underlying_price

    def chain_prefetch_superseded(self, generation: int) -> bool:
        with self.chain_prefetch_lock:
            return generation != self.chain_prefetch_generation

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

        started_at = perf_counter()
        context = self.chain_context(
            normalized_ticker,
            expiration,
            current_date=current_date,
            stop_event=stop_event,
        )
        if stop_event.is_set():
            return
        context_ms = elapsed_ms(started_at)
        display_strikes = capped_chain_strikes(
            context.strikes,
            context.underlying_price,
            self.max_chain_strikes,
        )
        display_strike_set = set(display_strikes)
        display_contracts = [
            contract
            for contract in context.contracts
            if contract.strike in display_strike_set
        ]
        live_strikes = capped_chain_strikes(
            display_strikes,
            context.underlying_price,
            self.max_chain_stream_strikes,
        )
        live_strike_set = set(live_strikes)
        stream_contracts = nearest_contracts_first(
            [
                contract
                for contract in display_contracts
                if contract.strike in live_strike_set
            ],
            context.underlying_price,
        )
        # Strikes outside the live window are quoted in rotating batches.
        rotation = (
            OptionChainRotation(
                context.ticker,
                context.expiration,
                display_strikes,
                display_contracts,
                live_strikes,
                context.underlying_price,
            )
            if len(live_strikes) < len(display_strikes)
            else None
        )
        if len(display_strikes) < len(context.strikes) or rotation is not None:
            logger.info(
                "Options chain stream strikes capped ticker=%s expiration=%s "
                "requested_strikes=%s displayed_strikes=%s live_strikes=%s",
                context.ticker,
                context.expiration,
                len(context.strikes),
                len(display_strikes),
                len(live_strikes),
            )
        quotes = self.cached_chain_quotes(display_contracts)
        delta_bounds = option_chain_delta_bounds(display_strikes, quotes)
        if rotation is not None:
            rotation.observe(quotes, delta_bounds)
        timing = ChainStreamTiming(
            context.ticker,
            context.expiration,
            started_at,
            context_ms,
            display_strikes,
            len(context.strikes),
        )
        timing.observe(quotes, delta_bounds)
        streaming_message = (
            f"Streaming {len(display_strikes)} strike(s) for "
            f"{context.ticker} {context.expiration}."
        )

        yield OptionChainLiveMessage(
            type="snapshot",
            ticker=context.ticker,
            expiration=context.expiration,
            rows=option_chain_rows(display_strikes, quotes),
            message=streaming_message,
        )

        stream_warning = None
        for quote_batch in self.chain_stream_provider.stream_chain_quotes(
            stream_contracts,
            stop_event,
            rotation,
        ):
            if stop_event.is_set():
                break
            if isinstance(quote_batch, OptionChainStreamNotice):
                stream_warning = quote_batch.warning
                yield OptionChainLiveMessage(
                    type="snapshot",
                    ticker=context.ticker,
                    expiration=context.expiration,
                    rows=option_chain_rows(display_strikes, quotes),
                    message=streaming_message,
                    warning=stream_warning,
                )
                continue

            changed_quotes = dict(quote_batch)
            quotes.update(changed_quotes)
            self.remember_chain_quotes(display_contracts, changed_quotes)
            rows = option_chain_rows(display_strikes, quotes)
            next_delta_bounds = option_chain_delta_bounds(
                display_strikes,
                quotes,
            )
            if rotation is not None:
                rotation.observe(quotes, next_delta_bounds)
            timing.observe(quotes, next_delta_bounds)
            if next_delta_bounds != delta_bounds:
                delta_bounds = next_delta_bounds
                yield OptionChainLiveMessage(
                    type="snapshot",
                    ticker=context.ticker,
                    expiration=context.expiration,
                    rows=rows,
                    message=streaming_message,
                    warning=stream_warning,
                )
                continue
            for changed_strike in sorted({key[0] for key, _quote in quote_batch}):
                row = next(
                    (
                        row
                        for row in rows
                        if row.strike == changed_strike
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
        stop_event: Event | None = None,
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

        strikes = option_chain_strikes(metadata.strikes)
        contracts = self.chain_contracts(
            ticker,
            expiration,
            strikes,
            cacheable=not metadata.expirations or expiration in metadata.expirations,
            stop_event=stop_event,
            underlying_price=underlying_price,
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
        stop_event: Event | None = None,
        underlying_price: float | None = None,
        fallback_without_price: bool = True,
        background: bool = False,
    ) -> list[ScannerOptionContract]:
        fallback_strikes = (
            self.chain_fallback_strikes(strikes, underlying_price)
            if underlying_price is not None or fallback_without_price
            else []
        )
        if not cacheable:
            self.clear_contract_cache(ticker, expiration)
            return preferred_chain_contracts(
                self.chain_provider.fetch_chain_contract_hydration(
                    ticker,
                    expiration,
                    strikes,
                    stop_event,
                    fallback_strikes,
                ).contracts
            )

        key = (ticker, expiration)
        with self.contract_cache_lock:
            cached = self.cached_chain_contract_entries(ticker, expiration, strikes)
            skipped = self.contract_cache.chain_skipped_strikes(ticker, expiration)
            fallback_strike_set = set(fallback_strikes)
            requested_strikes = [
                strike
                for strike in strikes
                if any((strike, right) not in cached for right in OPTION_RIGHT_CODES)
                and (strike not in skipped or strike in fallback_strike_set)
            ]
            if not requested_strikes:
                logger.info(
                    "Option chain contract cache hit ticker=%s expiration=%s "
                    "strikes=%s contracts=%s",
                    ticker,
                    expiration,
                    len(strikes),
                    sum(1 for entry in cached.values() if entry),
                )
                return preferred_chain_contracts_from_entries(cached)

            in_flight = self.contract_cache_in_flight.get(key)
            if in_flight is None:
                in_flight = OptionChainContractsInFlight(
                    ready=Event(),
                    priority=ContractLookupPriority(background=background),
                )
                self.contract_cache_in_flight[key] = in_flight
                owner = True
                logger.info(
                    "Option chain contract cache miss ticker=%s expiration=%s "
                    "strikes=%s retry_strikes=%s retained_contracts=%s",
                    ticker,
                    expiration,
                    len(strikes),
                    len(requested_strikes),
                    sum(1 for entry in cached.values() if entry),
                )
            else:
                owner = False
                if not background:
                    in_flight.priority.promote()
                logger.info(
                    "Option chain contract cache sharing in-flight hydration "
                    "ticker=%s expiration=%s strikes=%s",
                    ticker,
                    expiration,
                    len(strikes),
                )

        if not owner:
            while not in_flight.ready.wait(timeout=0.05):
                if stop_event is not None and stop_event.is_set():
                    return preferred_chain_contracts_from_entries(cached)
            if in_flight.error is not None:
                raise in_flight.error
            with self.contract_cache_lock:
                return preferred_chain_contracts_from_entries(
                    self.cached_chain_contract_entries(ticker, expiration, strikes)
                )

        started_at = perf_counter()
        requested_strike_set = set(requested_strikes)
        resolved_keys = frozenset(
            key for key in cached if key[0] in requested_strike_set
        )
        try:
            hydration = self.chain_provider.fetch_chain_contract_hydration(
                ticker,
                expiration,
                requested_strikes,
                stop_event,
                [strike for strike in fallback_strikes if strike in requested_strike_set],
                resolved_keys,
                priority=in_flight.priority,
            )
        except BaseException as error:
            with self.contract_cache_lock:
                in_flight.error = error
                self.contract_cache_in_flight.pop(key, None)
                in_flight.ready.set()
            raise

        with self.contract_cache_lock:
            self.store_chain_hydration(
                ticker,
                expiration,
                requested_strikes,
                hydration,
                resolved_keys,
            )
            entries = self.cached_chain_contract_entries(ticker, expiration, strikes)
            self.contract_cache_in_flight.pop(key, None)
            in_flight.ready.set()

        contracts = preferred_chain_contracts_from_entries(entries)
        logger.info(
            "Option chain contract hydration ticker=%s expiration=%s state=%s "
            "requested_strikes=%s resolved_strikes=%s timed_out_strikes=%s "
            "invalid_strikes=%s skipped_strikes=%s contracts=%s ib_wait_ms=%.1f",
            ticker,
            expiration,
            "partial" if hydration.timed_out_strikes else "complete",
            len(requested_strikes),
            len({contract.strike for contract in hydration.contracts}),
            len(hydration.timed_out_strikes),
            len(hydration.invalid_strikes),
            len(hydration.skipped_strikes),
            len(contracts),
            elapsed_ms(started_at),
        )
        return contracts

    def chain_fallback_strikes(
        self,
        strikes: list[float],
        underlying_price: float | None,
    ) -> list[float]:
        if underlying_price is None:
            return list(strikes)
        return capped_chain_strikes(
            strikes,
            underlying_price,
            self.chain_fallback_strike_count,
        )

    def cached_chain_contract_entries(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> dict[tuple[float, str], tuple[ScannerOptionContract, ...]]:
        lookups = [(expiration, strike) for strike in strikes]
        return {
            (strike, right): contracts
            for right in OPTION_RIGHT_CODES
            for (_expiration, strike), contracts in self.contract_cache.get_many(
                ticker,
                right,
                lookups,
            ).items()
        }

    def store_chain_hydration(
        self,
        ticker: str,
        expiration: str,
        requested_strikes: list[float],
        hydration: OptionChainContractHydration,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
    ) -> None:
        unsettled_strikes = hydration.timed_out_strikes | hydration.skipped_strikes
        resolved: dict[tuple[float, str], list[ScannerOptionContract]] = {}
        for contract in hydration.contracts:
            resolved.setdefault(
                (contract.strike, option_right_code(contract.right)),
                [],
            ).append(contract)
        for right in OPTION_RIGHT_CODES:
            self.contract_cache.store(
                ticker,
                right,
                {
                    (expiration, strike): resolved.get((strike, right), [])
                    for strike in requested_strikes
                    if (strike, right) in resolved
                    or (
                        strike not in unsettled_strikes
                        and (strike, right) not in resolved_keys
                    )
                },
            )
        if hydration.skipped_strikes:
            self.contract_cache.remember_chain_skipped_strikes(
                ticker,
                expiration,
                hydration.skipped_strikes,
            )

    def clear_contract_cache(self, ticker: str, expiration: str) -> None:
        self.contract_cache.clear(ticker, expiration)

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
