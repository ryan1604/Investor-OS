from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import logging
from queue import Empty, SimpleQueue
from threading import Event, Lock, Thread
from time import monotonic, perf_counter

from ibapi.contract import Contract

from app.ib.app import (
    IB_INVALID_CONTRACT_CODES,
    IB_MARKET_DATA_LINE_LIMIT_CODE,
    US_MARKET_TIME_ZONE,
    IbPortfolioApp,
)
from app.ib.market_data_lines import market_data_line_budget
from app.ib.pacing import contract_details_limiter
from app.ib.contracts import (
    us_equity_contract,
    us_option_contract,
    us_option_universe_contract,
)
from app.options.client import (
    ContractLookupPriority,
    OptionChainContractHydration,
    OptionChainRotation,
    current_us_market_date,
    preferred_chain_contracts,
    OptionChainStreamNotice,
    OptionsDataUnavailable,
    ScannerContractSelection,
    ScannerOptionContract,
    ScannerOptionQuote,
)
from app.options.domain import OptionMetadata, to_option_quote
from app.options.store import CompletedDailyBar
from app.tickers import normalize_ticker
from app.schemas import OptionQuote

OPTION_MARKET_DATA_GENERIC_TICKS = "100,101,104,106"
OPTION_RIGHTS = ("C", "P")
EXACT_CONTRACT_LOOKUP_CONCURRENCY = 10
# Longest wait for a shared contract-details slot when the slot wait has its
# own limit; matches the limiter's stale-slot reclaim, so a slot always frees.
CONTRACT_DETAILS_SLOT_WAIT_SECONDS = 60
QUOTE_FIELDS = ("bid", "ask", "delta")
QUOTE_SETTLE_SECONDS = 0.3
logger = logging.getLogger(__name__)


def raise_invalid_ticker_if_needed(app, req_id: int, ticker: str) -> None:
    request_errors = getattr(app, "request_errors_by_req_id", None)
    if request_errors is None:
        return

    with app.lock:
        request_error = request_errors.pop(req_id, None)

    if request_error and request_error[0] in IB_INVALID_CONTRACT_CODES:
        raise OptionsDataUnavailable(f"Invalid ticker: {ticker}.")


def pop_invalid_contract_error(app, req_id: int) -> bool:
    request_errors = getattr(app, "request_errors_by_req_id", None)
    if request_errors is None:
        return False

    with app.lock:
        request_error = request_errors.pop(req_id, None)

    return bool(request_error and request_error[0] in IB_INVALID_CONTRACT_CODES)


class IbHistoricalDailyBarProvider:
    def __init__(self, app: IbPortfolioApp, *, timeout_seconds: int = 8) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[CompletedDailyBar]:
        if not self.app.isConnected():
            return []

        normalized_ticker = normalize_ticker(ticker)
        contract = us_equity_contract(normalized_ticker)
        duration_days = (end_date - start_date).days + 1

        with self.app.lock:
            req_id = self.app.next_historical_req_id
            self.app.next_historical_req_id += 1
            self.app.historical_bars[req_id] = []
            self.app.historical_req_tickers[req_id] = normalized_ticker
            ready = Event()
            self.app.historical_data_ready_by_req_id[req_id] = ready

        self.app.reqHistoricalData(
            req_id,
            contract,
            f"{end_date:%Y%m%d} 23:59:59 US/Eastern",
            f"{duration_days} D",
            "1 day",
            "TRADES",
            1,
            1,
            False,
            [],
        )
        completed = ready.wait(timeout=self.timeout_seconds)

        with self.app.lock:
            bars = list(self.app.historical_bars.pop(req_id, []))
            self.app.historical_req_tickers.pop(req_id, None)
            self.app.historical_data_ready_by_req_id.pop(req_id, None)

        raise_invalid_ticker_if_needed(self.app, req_id, normalized_ticker)
        if not completed:
            # Callers see no bars either way; this tells an IB-side delay apart
            # from an IB error, which the error callback logs separately.
            logger.warning(
                "Historical daily bars timed out ticker=%s req_id=%s "
                "duration_days=%s timeout_s=%s bars=%s",
                normalized_ticker,
                req_id,
                duration_days,
                self.timeout_seconds,
                len(bars),
            )
        return bars


class IbHistoricalDailyBarStreamProvider:
    def __init__(
        self,
        app: IbPortfolioApp,
        *,
        timeout_seconds: float = 8,
        wait_seconds: float = 1,
    ) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds
        self.wait_seconds = wait_seconds

    def stream_daily_bar_updates(
        self,
        ticker: str,
        stop_event: Event,
    ) -> Iterable[CompletedDailyBar]:
        if not self.app.isConnected():
            return

        normalized_ticker = normalize_ticker(ticker)
        snapshot_provider = IbHistoricalDailyBarProvider(
            self.app,
            timeout_seconds=self.timeout_seconds,
        )
        snapshot_bars = snapshot_provider.fetch_daily_bars(
            normalized_ticker,
            *current_daily_snapshot_range(),
        )
        active_bar = max(
            snapshot_bars,
            key=lambda bar: bar.trading_date,
            default=None,
        )
        contract = resolve_direct_market_data_contract(
            self.app,
            normalized_ticker,
            timeout_seconds=self.timeout_seconds,
        )

        with self.app.lock:
            chart_market_req_id = self.app.next_chart_market_req_id
            self.app.next_chart_market_req_id += 1
            self.app.chart_market_req_tickers[chart_market_req_id] = normalized_ticker
            self.app.chart_market_updates_by_req_id[chart_market_req_id] = []
            chart_market_ready = Event()
            self.app.chart_market_ready_by_req_id[chart_market_req_id] = (
                chart_market_ready
            )

        budget = market_data_line_budget(self.app)
        chart_lines = budget.acquire("chart", 1, stop_event=stop_event)
        try:
            if not chart_lines:
                return
            self.app.reqMarketDataType(3)
            self.app.reqMktData(
                chart_market_req_id,
                contract,
                "",
                False,
                False,
                [],
            )
            if active_bar is not None:
                yield active_bar

            while not stop_event.is_set():
                if not chart_market_ready.wait(self.wait_seconds):
                    continue

                with self.app.lock:
                    updates = list(
                        self.app.chart_market_updates_by_req_id.get(
                            chart_market_req_id,
                            [],
                        )
                    )
                    self.app.chart_market_updates_by_req_id[chart_market_req_id] = []
                    chart_market_ready.clear()

                for bar in updates:
                    active_bar = merge_daily_bar(active_bar, bar)
                    yield active_bar
        finally:
            if chart_lines:
                self.app.cancelMktData(chart_market_req_id)
                budget.release("chart", chart_lines)
            with self.app.lock:
                self.app.chart_market_req_tickers.pop(chart_market_req_id, None)
                self.app.chart_market_updates_by_req_id.pop(
                    chart_market_req_id,
                    None,
                )
                self.app.chart_market_ready_by_req_id.pop(chart_market_req_id, None)


def resolve_direct_market_data_contract(
    app: IbPortfolioApp,
    ticker: str,
    *,
    timeout_seconds: float,
) -> Contract:
    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    remaining_seconds = send_contract_details_request(
        app,
        req_id,
        us_equity_contract(ticker),
        timeout_seconds=timeout_seconds,
        urgent=True,
    )
    completed = ready.wait(timeout=remaining_seconds)

    with app.lock:
        contract_details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)

    raise_invalid_ticker_if_needed(app, req_id, ticker)
    if not completed:
        raise OptionsDataUnavailable(
            f"Market-data contract request timed out for {ticker}."
        )
    if not contract_details:
        raise OptionsDataUnavailable(
            f"Market-data contract is unavailable for {ticker}."
        )

    contract = contract_details[0].contract
    if not contract.primaryExchange:
        raise OptionsDataUnavailable(
            f"Primary market-data exchange is unavailable for {ticker}."
        )

    contract.exchange = contract.primaryExchange
    return contract


def current_daily_snapshot_range() -> tuple[date, date]:
    current_date = datetime.now(US_MARKET_TIME_ZONE).date()
    return current_date - timedelta(days=1), current_date


def merge_daily_bar(
    current_bar: CompletedDailyBar | None,
    next_bar: CompletedDailyBar,
) -> CompletedDailyBar:
    if current_bar is None or current_bar.trading_date != next_bar.trading_date:
        return next_bar

    return CompletedDailyBar(
        ticker=next_bar.ticker,
        trading_date=next_bar.trading_date,
        open=current_bar.open,
        high=max(current_bar.high, next_bar.high),
        low=min(current_bar.low, next_bar.low),
        close=next_bar.close,
        volume=current_bar.volume,
    )


class IbOptionMetadataProvider:
    def __init__(self, app: IbPortfolioApp, *, timeout_seconds: int = 8) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    def fetch_option_metadata(self, ticker: str) -> OptionMetadata:
        if not self.app.isConnected():
            raise OptionsDataUnavailable(
                "Options metadata is unavailable while IB is disconnected."
            )

        normalized_ticker = normalize_ticker(ticker)
        contract = us_equity_contract(normalized_ticker)

        with self.app.lock:
            contract_req_id = self.app.next_contract_details_req_id
            self.app.next_contract_details_req_id += 1
            self.app.contract_details[contract_req_id] = []
            contract_details_ready = Event()
            self.app.contract_details_ready_by_req_id[contract_req_id] = (
                contract_details_ready
            )

        remaining_seconds = send_contract_details_request(
            self.app,
            contract_req_id,
            contract,
            timeout_seconds=self.timeout_seconds,
            urgent=True,
            slot_timeout_seconds=CONTRACT_DETAILS_SLOT_WAIT_SECONDS,
        )
        contract_details_completed = contract_details_ready.wait(
            timeout=remaining_seconds
        )

        with self.app.lock:
            contract_details = self.app.contract_details.pop(contract_req_id, [])
            self.app.contract_details_ready_by_req_id.pop(contract_req_id, None)

        raise_invalid_ticker_if_needed(
            self.app,
            contract_req_id,
            normalized_ticker,
        )
        if not contract_details_completed:
            raise OptionsDataUnavailable(
                f"Options metadata request timed out for {normalized_ticker}."
            )
        if not contract_details:
            return OptionMetadata(expirations=[], strikes=[])

        underlying_con_id = contract_details[0].contract.conId
        with self.app.lock:
            option_req_id = self.app.next_option_params_req_id
            self.app.next_option_params_req_id += 1
            self.app.option_metadata[option_req_id] = OptionMetadata(
                expirations=[],
                strikes=[],
            )
            option_metadata_ready = Event()
            self.app.option_metadata_ready_by_req_id[option_req_id] = (
                option_metadata_ready
            )

        self.app.reqSecDefOptParams(
            option_req_id,
            normalized_ticker,
            "",
            "STK",
            underlying_con_id,
        )
        option_metadata_completed = option_metadata_ready.wait(
            timeout=self.timeout_seconds
        )

        with self.app.lock:
            metadata = self.app.option_metadata.pop(
                option_req_id,
                OptionMetadata(expirations=[], strikes=[]),
            )
            self.app.option_metadata_ready_by_req_id.pop(option_req_id, None)

        raise_invalid_ticker_if_needed(
            self.app,
            option_req_id,
            normalized_ticker,
        )
        if not option_metadata_completed:
            raise OptionsDataUnavailable(
                f"Options metadata request timed out for {normalized_ticker}."
            )
        return metadata


class IbOptionChainSnapshotProvider:
    def __init__(
        self,
        app: IbPortfolioApp,
        *,
        timeout_seconds: float = 4,
        contract_timeout_seconds: float = 8,
        hydration_timeout_seconds: float = 30,
        current_date_provider=current_us_market_date,
    ) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds
        self.contract_timeout_seconds = contract_timeout_seconds
        self.hydration_timeout_seconds = hydration_timeout_seconds
        self.current_date_provider = current_date_provider
        # Broad requests that timed out today go straight to exact lookups.
        self.broad_timeouts: dict[tuple[str, str], date] = {}
        self.broad_timeouts_lock = Lock()

    def fetch_chain_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
    ) -> list[ScannerOptionContract]:
        return preferred_chain_contracts(
            self.fetch_chain_contract_hydration(
                ticker,
                expiration,
                strikes,
            ).contracts
        )

    def fetch_chain_contract_hydration(
        self,
        ticker: str,
        expiration: str,
        strikes: list[float],
        stop_event: Event | None = None,
        fallback_strikes: list[float] | None = None,
        resolved_keys: frozenset[tuple[float, str]] = frozenset(),
        priority: ContractLookupPriority | None = None,
    ) -> OptionChainContractHydration:
        if not self.app.isConnected() or not strikes:
            return OptionChainContractHydration(contracts=[])

        normalized_ticker = normalize_ticker(ticker)
        started_at = perf_counter()
        deadline = monotonic() + max(0, self.hydration_timeout_seconds)
        strike_set = set(strikes)
        fallback_strikes = (
            strikes
            if fallback_strikes is None
            else [strike for strike in fallback_strikes if strike in strike_set]
        )
        strikes_by_right = {
            right: right_strikes
            for right in OPTION_RIGHTS
            if (
                right_strikes := {
                    strike for strike in strikes if (strike, right) not in resolved_keys
                }
            )
        }
        if not strikes_by_right:
            return OptionChainContractHydration(contracts=[])

        hydrations, fallback_mode = self._fetch_broad_chain_contracts(
            normalized_ticker,
            expiration,
            strikes_by_right,
            deadline,
            stop_event,
            priority,
        )
        fallback_rights = [right for right in strikes_by_right if right not in hydrations]
        fallback_strikes_by_right = {
            right: [
                strike for strike in fallback_strikes if strike in strikes_by_right[right]
            ]
            for right in fallback_rights
        }
        if fallback_rights:
            # Calls and puts fall back together so neither waits for the other.
            with ThreadPoolExecutor(
                max_workers=len(fallback_rights),
                thread_name_prefix="ib-chain-contracts",
            ) as executor:
                futures = {
                    right: executor.submit(
                        self._fetch_exact_chain_right_contracts,
                        normalized_ticker,
                        expiration,
                        strikes_by_right[right],
                        fallback_strikes_by_right[right],
                        right,
                        deadline,
                        stop_event,
                        priority,
                    )
                    for right in fallback_rights
                }
                hydrations.update(
                    {right: future.result() for right, future in futures.items()}
                )
        for right in strikes_by_right:
            logger.info(
                "Option chain contract right ticker=%s expiration=%s right=%s "
                "mode=%s strikes=%s elapsed_ms=%.1f",
                normalized_ticker,
                expiration,
                right,
                fallback_mode if right in fallback_rights else "broad",
                len(fallback_strikes_by_right.get(right, strikes_by_right[right])),
                elapsed_ms(started_at),
            )

        ordered = [hydrations[right] for right in strikes_by_right]
        timed_out_strikes = frozenset().union(
            *(hydration.timed_out_strikes for hydration in ordered)
        )
        invalid_strikes = frozenset().union(
            *(hydration.invalid_strikes for hydration in ordered)
        )
        skipped_strikes = frozenset().union(
            *(hydration.skipped_strikes for hydration in ordered)
        )
        return OptionChainContractHydration(
            contracts=[
                contract for hydration in ordered for contract in hydration.contracts
            ],
            timed_out_strikes=timed_out_strikes,
            invalid_strikes=invalid_strikes - timed_out_strikes,
            skipped_strikes=skipped_strikes,
        )

    def _fetch_broad_chain_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes_by_right: dict[str, set[float]],
        deadline: float,
        stop_event: Event | None,
        priority: ContractLookupPriority | None,
    ) -> tuple[dict[str, OptionChainContractHydration], str]:
        """Return the rights one broad request settled and the fallback mode."""
        request_timeout = remaining_contract_timeout(
            self.contract_timeout_seconds,
            deadline,
        )
        if request_timeout <= 0 or (stop_event is not None and stop_event.is_set()):
            return {
                right: OptionChainContractHydration(
                    contracts=[],
                    timed_out_strikes=frozenset(right_strikes),
                )
                for right, right_strikes in strikes_by_right.items()
            }, "exact_fallback"
        if self._broad_timed_out_today(ticker, expiration):
            return {}, "exact_known_broad_timeout"

        try:
            # IB works through broad requests one at a time, taking seconds on
            # expirations it has not loaded recently, so one request covers
            # both rights instead of queueing a second.
            selection = fetch_standard_option_contracts(
                self.app,
                ticker,
                expiration,
                strikes_by_right,
                timeout_seconds=request_timeout,
                stop_event=stop_event,
                priority=priority,
            )
        except OptionsDataUnavailable as error:
            if not is_contract_timeout(error):
                raise
            if stop_event is None or not stop_event.is_set():
                self._remember_broad_timeout(ticker, expiration)
            logger.info(
                "Broad option contract request timed out; falling back to exact "
                "contracts ticker=%s expiration=%s rights=%s",
                ticker,
                expiration,
                ",".join(strikes_by_right),
            )
            return {}, "exact_fallback"

        hydrations = {}
        for right, right_strikes in strikes_by_right.items():
            contracts = [
                contract
                for contract in selection.contracts
                if option_right_code(contract.right) == right
            ]
            hydrations[right] = OptionChainContractHydration(
                contracts=contracts,
                invalid_strikes=frozenset(
                    right_strikes - {contract.strike for contract in contracts}
                ),
            )
        return hydrations, "exact_fallback"

    def _fetch_exact_chain_right_contracts(
        self,
        ticker: str,
        expiration: str,
        strikes: set[float],
        fallback_strikes: list[float],
        right: str,
        deadline: float,
        stop_event: Event | None,
        priority: ContractLookupPriority | None,
    ) -> OptionChainContractHydration:
        exact = fetch_exact_chain_contract_hydration(
            self.app,
            ticker,
            expiration,
            fallback_strikes,
            right,
            timeout_seconds=self.contract_timeout_seconds,
            deadline=deadline,
            stop_event=stop_event,
            priority=priority,
        )
        return OptionChainContractHydration(
            contracts=exact.contracts,
            timed_out_strikes=exact.timed_out_strikes,
            invalid_strikes=exact.invalid_strikes,
            skipped_strikes=frozenset(strikes - set(fallback_strikes)),
        )

    def _broad_timed_out_today(self, ticker: str, expiration: str) -> bool:
        with self.broad_timeouts_lock:
            return (
                self.broad_timeouts.get((ticker, expiration))
                == self.current_date_provider()
            )

    def _remember_broad_timeout(self, ticker: str, expiration: str) -> None:
        with self.broad_timeouts_lock:
            self.broad_timeouts[(ticker, expiration)] = self.current_date_provider()

    def fetch_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
    ) -> dict[tuple[float, str], OptionQuote]:
        if not self.app.isConnected() or not contracts:
            return {}

        budget = market_data_line_budget(self.app)
        raw_quotes: dict[tuple[float, str], dict[str, float | int | None]] = {}
        remaining = list(contracts)
        while remaining:
            granted = budget.acquire(
                "chain",
                len(remaining),
                timeout=self.timeout_seconds,
            )
            if not granted:
                break
            subscriptions = OptionMarketDataSubscriptions(
                self.app,
                remaining[:granted],
                snapshot=False,
            )
            remaining = remaining[granted:]
            try:
                started_at = perf_counter()
                subscriptions.open()
                wait_for_quote_fields(
                    self.app,
                    subscriptions.req_ids,
                    subscriptions.ready,
                    max_wait_seconds=self.timeout_seconds,
                    started_at=started_at,
                )
                raw_quotes.update(subscriptions.snapshot_values())
            finally:
                subscriptions.close()
                budget.release("chain", granted)

        return {
            key: to_option_quote(
                values,
                strike=key[0],
                right=key[1],
            )
            for key, values in raw_quotes.items()
        }


class IbOptionChainStreamProvider:
    def __init__(
        self,
        app: IbPortfolioApp,
        *,
        wait_seconds: float = 1,
        rotation_lines: int = 10,
        rotation_wait_seconds: float = 4,
        rotation_idle_seconds: float = 1,
    ) -> None:
        self.app = app
        self.wait_seconds = wait_seconds
        self.rotation_lines = max(2, rotation_lines)
        self.rotation_wait_seconds = rotation_wait_seconds
        self.rotation_idle_seconds = rotation_idle_seconds

    def stream_chain_quotes(
        self,
        contracts: list[ScannerOptionContract],
        stop_event: Event,
        rotation: OptionChainRotation | None = None,
    ) -> Iterable[list[tuple[tuple[float, str], OptionQuote]]]:
        if not self.app.isConnected() or not contracts:
            return

        latest_values: dict[tuple[float, str], dict[str, float | int | None]] = {}
        budget = market_data_line_budget(self.app)
        subscriptions = OptionMarketDataSubscriptions(
            self.app,
            [],
            snapshot=False,
        )
        warning = None
        rotated_quotes: SimpleQueue[list[tuple[tuple[float, str], OptionQuote]]] = (
            SimpleQueue()
        )
        rotation_stop = Event()
        rotation_worker = None
        if rotation is not None:
            rotation_worker = Thread(
                target=self._rotate_outer_strikes,
                args=(
                    rotation,
                    AnyEvent(stop_event, rotation_stop),
                    rotation_stop,
                    rotated_quotes,
                    subscriptions.ready,
                ),
                name="option-chain-rotation",
                daemon=True,
            )
            rotation_worker.start()

        try:
            while not stop_event.is_set():
                live_contracts = (
                    rotation.live_contracts() if rotation is not None else contracts
                )
                budget.release(
                    "chain",
                    subscriptions.unsubscribe_except(live_contracts),
                )
                subscribed_keys = set(subscriptions.keys())
                waiting = [
                    contract
                    for contract in live_contracts
                    if option_contract_key(contract) not in subscribed_keys
                ]
                if waiting:
                    granted = budget.try_acquire(
                        "chain",
                        len(waiting),
                        owner=subscriptions,
                    )
                    subscriptions.subscribe(waiting[:granted])
                next_warning = chain_stream_warning(
                    len(live_contracts),
                    len(subscriptions.contracts),
                    subscriptions.line_limited_count(),
                )
                if next_warning != warning:
                    warning = next_warning
                    yield OptionChainStreamNotice(warning=warning)

                if not subscriptions.ready.wait(self.wait_seconds):
                    continue

                updates_started_at = perf_counter()
                changed_quotes: list[tuple[tuple[float, str], OptionQuote]] = []
                for key, current_values in subscriptions.changed_values(
                    latest_values
                ):
                    latest_values[key] = current_values
                    changed_quotes.append(
                        (
                            key,
                            to_option_quote(
                                current_values,
                                strike=key[0],
                                right=key[1],
                            )
                        )
                    )
                while True:
                    try:
                        changed_quotes.extend(rotated_quotes.get_nowait())
                    except Empty:
                        break

                if changed_quotes:
                    yield changed_quotes
                logger.info(
                    "Option chain stream updates ticker=%s expiration=%s "
                    "changed_quotes=%s update_ms=%.1f",
                    subscriptions.ticker,
                    subscriptions.expiration,
                    len(changed_quotes),
                    elapsed_ms(updates_started_at),
                )
        finally:
            rotation_stop.set()
            if rotation_worker is not None:
                rotation_worker.join(timeout=self.rotation_wait_seconds + 1)
            budget.clear_pending(subscriptions)
            subscriptions.close()
            budget.release("chain", len(subscriptions.contracts))

    def _rotate_outer_strikes(
        self,
        rotation: OptionChainRotation,
        stop_event: AnyEvent,
        idle_event: Event,
        results: SimpleQueue[list[tuple[tuple[float, str], OptionQuote]]],
        wake: Event,
    ) -> None:
        """Quote outer strikes in small batches through the reserved lines:
        subscribe, take the quotes once complete or at the maximum wait,
        cancel, then continue with the next batch."""
        budget = market_data_line_budget(self.app)
        batch: list[ScannerOptionContract] = []
        try:
            while not stop_event.is_set():
                batch = batch or rotation.next_batch(self.rotation_lines)
                if not batch:
                    idle_event.wait(self.rotation_idle_seconds)
                    continue
                if not budget.try_acquire("chain", len(batch), minimum=len(batch)):
                    idle_event.wait(0.25)
                    continue
                try:
                    subscriptions = OptionMarketDataSubscriptions(
                        self.app,
                        batch,
                        snapshot=False,
                    )
                    try:
                        started_at = perf_counter()
                        subscriptions.open()
                        wait_for_quote_fields(
                            self.app,
                            subscriptions.req_ids,
                            subscriptions.ready,
                            max_wait_seconds=self.rotation_wait_seconds,
                            cancel_event=stop_event,
                            started_at=started_at,
                        )
                        values = subscriptions.snapshot_values()
                    finally:
                        subscriptions.close()
                finally:
                    budget.release("chain", len(batch))
                batch = []
                # Keep the last good quote for contracts that did not quote.
                quoted = {
                    key: current_values
                    for key, current_values in values.items()
                    if any(field != "local_symbol" for field in current_values)
                }
                rotation.record(quoted)
                if quoted and not stop_event.is_set():
                    results.put(
                        [
                            (
                                key,
                                to_option_quote(
                                    current_values,
                                    strike=key[0],
                                    right=key[1],
                                ),
                            )
                            for key, current_values in quoted.items()
                        ]
                    )
                    wake.set()
        except Exception:
            logger.exception(
                "Option chain rotation failed ticker=%s expiration=%s",
                rotation.ticker,
                rotation.expiration,
            )


class ScannerQuoteSubscription:
    """One contract's quote in the scanner's rolling window."""

    def __init__(self, index: int, contract: ScannerOptionContract) -> None:
        self.index = index
        self.contract = contract
        self.started_at = monotonic()
        self.present_fields = 0
        self.changed_at: float | None = None

    def outcome(
        self,
        values: dict[str, float | int | None],
        now: float,
        *,
        line_limited: bool,
        max_wait_seconds: float,
        settle_seconds: float,
    ) -> str | None:
        """Return why this quote is finished, or None while it should wait."""
        if line_limited:
            return "limited"
        has_bid, has_ask, has_delta = (
            clean_quote_value(values.get(field)) is not None for field in QUOTE_FIELDS
        )
        present_fields = has_bid + has_ask + has_delta
        if present_fields != self.present_fields:
            self.present_fields = present_fields
            self.changed_at = now
        if present_fields == len(QUOTE_FIELDS):
            return "complete"
        # Same rule as a whole batch in wait_for_quote_fields: only a missing
        # bid, common on far strikes, may end the wait before the maximum.
        if (
            has_delta
            and (has_bid or has_ask)
            and now - self.changed_at >= settle_seconds
        ):
            return "settled"
        if now - self.started_at >= max_wait_seconds:
            return "timed_out"
        return None


class IbOptionScannerProvider:
    def __init__(
        self,
        app: IbPortfolioApp,
        *,
        contract_timeout_seconds: float = 8,
        quote_wait_seconds: float = 4,
        quote_settle_seconds: float = QUOTE_SETTLE_SECONDS,
        quote_window_size: int = 40,
    ) -> None:
        self.app = app
        self.contract_timeout_seconds = contract_timeout_seconds
        self.quote_wait_seconds = quote_wait_seconds
        self.quote_settle_seconds = quote_settle_seconds
        self.quote_window_size = max(1, quote_window_size)
        self.active_req_ids: set[int] = set()
        self.active_req_ids_lock = Lock()

    def fetch_option_contracts(
        self,
        ticker: str,
        lookups: list[tuple[str, float]],
        right: str,
        cancel_event: Event,
    ) -> ScannerContractSelection:
        if not self.app.isConnected():
            raise OptionsDataUnavailable(
                "Options scanning is unavailable while IB is disconnected."
            )

        normalized_ticker = normalize_ticker(ticker)
        contracts: list[ScannerOptionContract] = []
        started_at = perf_counter()
        invalid_lookups: set[tuple[str, float]] = set()
        timed_out_lookups: set[tuple[str, float]] = set()
        results = fetch_exact_contract_lookups(
            self.app,
            normalized_ticker,
            lookups,
            right,
            timeout_seconds=self.contract_timeout_seconds,
            stop_event=cancel_event,
            # Concurrent tickers queue for the shared slots; that wait is not
            # an IB timeout and must not drop the strike from the scan.
            slot_timeout_seconds=CONTRACT_DETAILS_SLOT_WAIT_SECONDS,
        )
        for lookup in lookups:
            resolved_contracts = results[lookup]
            if resolved_contracts is None:
                timed_out_lookups.add(lookup)
            elif not resolved_contracts:
                invalid_lookups.add(lookup)
            else:
                contracts.extend(resolved_contracts)
        expirations = {expiration for expiration, _strike in lookups}
        strikes = {strike for _expiration, strike in lookups}
        logger.info(
            "Options scanner contracts ticker=%s right=%s expirations=%s "
            "strikes=%s requests=%s contracts=%s invalid_strikes=%s "
            "timed_out_strikes=%s elapsed_ms=%.1f",
            normalized_ticker,
            right,
            len(expirations),
            len(strikes),
            len(lookups),
            len(contracts),
            len(invalid_lookups),
            len(timed_out_lookups),
            elapsed_ms(started_at),
        )
        return ScannerContractSelection(
            contracts=contracts,
            excluded_contracts=len(invalid_lookups) + len(timed_out_lookups),
            invalid_lookups=frozenset(invalid_lookups),
            timed_out_lookups=frozenset(timed_out_lookups),
        )

    def fetch_quotes(
        self,
        contracts: list[ScannerOptionContract],
        cancel_event: Event,
    ) -> list[ScannerOptionQuote]:
        """Quote contracts through a rolling window of market-data lines.

        Each contract frees its line as soon as its own quote is usable, so a
        greek IB computes late no longer holds lines the rest of a batch has
        finished with. The window refills without waiting while lines are
        free and shrinks when higher-priority groups need them.
        """
        started_at = perf_counter()
        budget = market_data_line_budget(self.app)
        pending = list(reversed(list(enumerate(contracts))))
        active: dict[int, ScannerQuoteSubscription] = {}
        ready = Event()
        quotes: list[tuple[int, ScannerOptionQuote]] = []
        outcomes: dict[str, int] = {}
        quote_ms: list[float] = []
        limit_errors: dict[int, int] = {}
        peak_window = 0
        self.app.reqMarketDataType(3)
        try:
            while not cancel_event.is_set():
                wanted = min(self.quote_window_size - len(active), len(pending))
                if wanted:
                    granted = (
                        budget.try_acquire("screener", wanted)
                        if active
                        else budget.acquire("screener", wanted, stop_event=cancel_event)
                    )
                    self._subscribe_quotes(
                        [pending.pop() for _ in range(granted)],
                        active,
                        ready,
                    )
                    peak_window = max(peak_window, len(active))
                if not active:
                    break

                ready.clear()
                now = monotonic()
                limited = line_limited_req_ids(self.app, active)
                with self.app.lock:
                    values_by_req_id = {
                        req_id: self.app.option_market_data.get(req_id, {}).copy()
                        for req_id in active
                    }
                finished = {}
                for req_id, subscription in active.items():
                    outcome = subscription.outcome(
                        values_by_req_id[req_id],
                        now,
                        line_limited=req_id in limited,
                        max_wait_seconds=self.quote_wait_seconds,
                        settle_seconds=self.quote_settle_seconds,
                    )
                    if outcome is not None:
                        finished[req_id] = outcome
                for req_id, outcome in finished.items():
                    subscription = active.pop(req_id)
                    outcomes[outcome] = outcomes.get(outcome, 0) + 1
                    quote_ms.append((now - subscription.started_at) * 1_000)
                    quotes.append(
                        (
                            subscription.index,
                            scanner_quote(
                                subscription.contract,
                                values_by_req_id[req_id],
                                line_limited=req_id in limited,
                            ),
                        )
                    )
                if finished:
                    for code, count in limit_error_counts(self.app, finished).items():
                        limit_errors[code] = limit_errors.get(code, 0) + count
                    self._release_quote_requests(list(finished))
                    budget.release("screener", len(finished))
                else:
                    ready.wait(0.05)
            # Cancelled: return what the unfinished quotes have so far.
            with self.app.lock:
                quotes.extend(
                    (
                        subscription.index,
                        scanner_quote(
                            subscription.contract,
                            self.app.option_market_data.get(req_id, {}),
                            line_limited=False,
                        ),
                    )
                    for req_id, subscription in active.items()
                )
        finally:
            self._release_quote_requests(list(active))
            budget.release("screener", len(active))

        ordered = [quote for _index, quote in sorted(quotes, key=lambda item: item[0])]
        quote_ms.sort()
        logger.info(
            "Options scanner quotes ticker=%s contracts=%s peak_window=%s "
            "outcomes=%s quote_p50_ms=%s quote_p90_ms=%s missing_bid=%s "
            "missing_ask=%s missing_delta=%s limit_errors=%s peak_lines=%s "
            "elapsed_ms=%.1f",
            contracts[0].ticker if contracts else "",
            len(ordered),
            peak_window,
            outcomes,
            percentile_ms(quote_ms, 0.5),
            percentile_ms(quote_ms, 0.9),
            sum(1 for quote in ordered if quote.bid is None),
            sum(1 for quote in ordered if quote.ask is None),
            sum(1 for quote in ordered if quote.delta is None),
            limit_errors,
            (market_data_line_usage(self.app) or (None, None))[1],
            elapsed_ms(started_at),
        )
        return ordered

    def _subscribe_quotes(
        self,
        pending: list[tuple[int, ScannerOptionContract]],
        active: dict[int, ScannerQuoteSubscription],
        ready: Event,
    ) -> None:
        requests = []
        with self.app.lock:
            for index, contract in pending:
                req_id = self.app.next_option_market_req_id
                self.app.next_option_market_req_id += 1
                self.app.option_market_req_to_key[req_id] = contract.con_id
                self.app.option_market_data[req_id] = {}
                self.app.option_market_ready_by_req_id[req_id] = ready
                requests.append(
                    (
                        req_id,
                        scanner_market_data_contract(contract),
                        OPTION_MARKET_DATA_GENERIC_TICKS,
                        False,
                        False,
                        [],
                    )
                )
                active[req_id] = ScannerQuoteSubscription(index, contract)
        with self.active_req_ids_lock:
            self.active_req_ids.update(request[0] for request in requests)
        for request in requests:
            self.app.reqMktData(*request)

    def _release_quote_requests(self, req_ids: list[int]) -> None:
        for req_id in req_ids:
            self.app.cancelMktData(req_id)
        with self.app.lock:
            for req_id in req_ids:
                self.app.option_market_req_to_key.pop(req_id, None)
                self.app.option_market_data.pop(req_id, None)
                self.app.option_market_ready_by_req_id.pop(req_id, None)
        forget_limit_errors(self.app, req_ids)
        with self.active_req_ids_lock:
            self.active_req_ids.difference_update(req_ids)

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
        if not self.app.isConnected():
            raise OptionsDataUnavailable(
                "Option quote refresh is unavailable while IB is disconnected."
            )

        normalized_ticker = normalize_ticker(ticker)
        contracts = self._resolve_option_contracts(
            normalized_ticker,
            expiration,
            strike,
            right,
        )
        selected = select_refreshed_contract(
            contracts,
            con_id=con_id,
            local_symbol=local_symbol,
        )
        if selected is None:
            raise OptionsDataUnavailable(
                "The selected option contract can no longer be resolved."
            )

        budget = market_data_line_budget(self.app)
        if not budget.acquire("quote_refresh", 1, timeout=self.quote_wait_seconds):
            raise OptionsDataUnavailable(
                "No IB market-data line is free for the quote refresh. "
                "Try again shortly."
            )
        try:
            quotes = self._fetch_quote_batch([selected], Event())
        finally:
            budget.release("quote_refresh", 1)
        if not quotes:
            raise OptionsDataUnavailable(
                "The selected option contract could not be quoted."
            )
        return quotes[0]

    def cancel(self) -> None:
        with self.active_req_ids_lock:
            req_ids = list(self.active_req_ids)
        for req_id in req_ids:
            self.app.cancelMktData(req_id)

    def _resolve_option_contracts(
        self,
        ticker: str,
        expiration: str,
        strike: float,
        right: str,
    ) -> list[ScannerOptionContract]:
        with self.app.lock:
            req_id = self.app.next_contract_details_req_id
            self.app.next_contract_details_req_id += 1
            self.app.contract_details[req_id] = []
            ready = Event()
            self.app.contract_details_ready_by_req_id[req_id] = ready

        remaining_seconds = send_contract_details_request(
            self.app,
            req_id,
            us_option_contract(
                ticker,
                expiration=expiration,
                strike=strike,
                right=right,
            ),
            timeout_seconds=self.contract_timeout_seconds,
            urgent=True,
        )
        completed = ready.wait(timeout=remaining_seconds)
        with self.app.lock:
            details = self.app.contract_details.pop(req_id, [])
            self.app.contract_details_ready_by_req_id.pop(req_id, None)

        raise_invalid_ticker_if_needed(self.app, req_id, ticker)
        if not completed:
            raise OptionsDataUnavailable(
                f"Option contract request timed out for {ticker} {expiration}."
            )

        return [
            scanner_contract(detail.contract)
            for detail in details
            if is_exact_standard_option_contract(
                detail.contract,
                ticker=ticker,
                expiration=expiration,
                strike=strike,
                right=right,
            )
        ]

    def _fetch_quote_batch(
        self,
        contracts: list[ScannerOptionContract],
        cancel_event: Event,
    ) -> list[ScannerOptionQuote]:
        req_ids: dict[int, ScannerOptionContract] = {}
        requests = []
        ready = Event()
        with self.app.lock:
            for contract in contracts:
                req_id = self.app.next_option_market_req_id
                self.app.next_option_market_req_id += 1
                self.app.option_market_req_to_key[req_id] = contract.con_id
                self.app.option_market_data[req_id] = {}
                self.app.option_market_ready_by_req_id[req_id] = ready
                req_ids[req_id] = contract
                requests.append(
                    (
                        req_id,
                        scanner_market_data_contract(contract),
                        OPTION_MARKET_DATA_GENERIC_TICKS,
                        False,
                        False,
                        [],
                    )
                )

        with self.active_req_ids_lock:
            self.active_req_ids.update(req_ids)
        try:
            started_at = perf_counter()
            self.app.reqMarketDataType(3)
            for request in requests:
                self.app.reqMktData(*request)
            line_usage = market_data_line_usage(self.app)
            timing = wait_for_quote_fields(
                self.app,
                list(req_ids),
                ready,
                max_wait_seconds=self.quote_wait_seconds,
                settle_seconds=self.quote_settle_seconds,
                cancel_event=cancel_event,
                started_at=started_at,
            )
            with self.app.lock:
                values_by_req_id = {
                    req_id: self.app.option_market_data.get(req_id, {}).copy()
                    for req_id in req_ids
                }
            missing = missing_quote_field_counts(values_by_req_id)
            line_limited = line_limited_req_ids(self.app, req_ids)
            logger.info(
                "Options scanner quote batch ticker=%s contracts=%s "
                "missing_bid=%s missing_ask=%s missing_delta=%s "
                "first_data_ms=%s complete_ms=%s last_change_ms=%s "
                "limit_errors=%s active_lines=%s peak_lines=%s elapsed_ms=%.1f",
                contracts[0].ticker if contracts else "",
                len(contracts),
                missing["bid"],
                missing["ask"],
                missing["delta"],
                *timing,
                limit_error_counts(self.app, req_ids),
                line_usage[0] if line_usage else None,
                line_usage[1] if line_usage else None,
                elapsed_ms(started_at),
            )
            return [
                scanner_quote(
                    contract,
                    values_by_req_id[req_id],
                    line_limited=req_id in line_limited,
                )
                for req_id, contract in req_ids.items()
            ]
        finally:
            self._release_quote_requests(list(req_ids))


def scanner_quote(
    contract: ScannerOptionContract,
    values: dict[str, float | int | None],
    *,
    line_limited: bool,
) -> ScannerOptionQuote:
    return ScannerOptionQuote(
        contract=contract,
        bid=clean_quote_value(values.get("bid")),
        ask=clean_quote_value(values.get("ask")),
        delta=clean_quote_value(values.get("delta")),
        line_limited=line_limited,
    )


def percentile_ms(sorted_values: list[float], fraction: float) -> str | None:
    if not sorted_values:
        return None
    return f"{sorted_values[int(fraction * (len(sorted_values) - 1))]:.0f}"


def is_standard_option_contract(
    contract: Contract,
    *,
    ticker: str,
    expiration: str,
    allowed_strikes: set[float],
    right: str,
) -> bool:
    return (
        contract.secType == "OPT"
        and contract.symbol == ticker
        and contract.currency == "USD"
        and contract.right in {right, "PUT" if right == "P" else "CALL"}
        and contract.multiplier == "100"
        and contract.lastTradeDateOrContractMonth[:8]
        == expiration.replace("-", "")
        and contract.strike in allowed_strikes
        and contract.strike > 0
        and has_usable_trading_class(contract)
        and contract.conId > 0
        and bool(contract.localSymbol)
    )


def fetch_standard_option_contracts(
    app: IbPortfolioApp,
    ticker: str,
    expiration: str,
    strikes_by_right: dict[str, set[float]],
    *,
    timeout_seconds: float,
    stop_event: Event | None = None,
    priority: ContractLookupPriority | None = None,
) -> ScannerContractSelection:
    """Resolve an expiration's standard contracts for each right in one request."""
    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    (only_right,) = strikes_by_right if len(strikes_by_right) == 1 else ("",)
    remaining_seconds = send_contract_details_request(
        app,
        req_id,
        us_option_universe_contract(
            ticker,
            expiration=expiration,
            right=only_right,
        ),
        timeout_seconds=timeout_seconds,
        stop_event=stop_event,
        priority=priority,
    )
    completed = wait_for_contract_details(ready, remaining_seconds, stop_event)
    with app.lock:
        details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)

    raise_invalid_ticker_if_needed(app, req_id, ticker)
    if not completed:
        raise OptionsDataUnavailable(
            f"Option contract request timed out for {ticker} {expiration}."
        )

    contracts = [
        scanner_contract(detail.contract)
        for detail in details
        if any(
            is_standard_option_contract(
                detail.contract,
                ticker=ticker,
                expiration=expiration,
                allowed_strikes=allowed_strikes,
                right=right,
            )
            for right, allowed_strikes in strikes_by_right.items()
        )
    ]
    return ScannerContractSelection(
        contracts=contracts,
        excluded_contracts=len(details) - len(contracts),
    )


def fetch_exact_chain_contracts(
    app: IbPortfolioApp,
    ticker: str,
    expiration: str,
    strikes: list[float],
    right: str,
    *,
    timeout_seconds: float,
) -> list[ScannerOptionContract]:
    return fetch_exact_chain_contract_hydration(
        app,
        ticker,
        expiration,
        strikes,
        right,
        timeout_seconds=timeout_seconds,
    ).contracts


def fetch_exact_chain_contract_hydration(
    app: IbPortfolioApp,
    ticker: str,
    expiration: str,
    strikes: list[float],
    right: str,
    *,
    timeout_seconds: float,
    deadline: float | None = None,
    stop_event: Event | None = None,
    priority: ContractLookupPriority | None = None,
) -> OptionChainContractHydration:
    results = fetch_exact_contract_lookups(
        app,
        ticker,
        [(expiration, strike) for strike in strikes],
        right,
        timeout_seconds=timeout_seconds,
        deadline=deadline,
        stop_event=stop_event,
        priority=priority,
    )
    contracts: list[ScannerOptionContract] = []
    timed_out_strikes: set[float] = set()
    invalid_strikes: set[float] = set()
    for strike in strikes:
        resolved_contracts = results[(expiration, strike)]
        if resolved_contracts is None:
            timed_out_strikes.add(strike)
        elif not resolved_contracts:
            invalid_strikes.add(strike)
        else:
            contracts.extend(resolved_contracts)
    return OptionChainContractHydration(
        contracts=contracts,
        timed_out_strikes=frozenset(timed_out_strikes),
        invalid_strikes=frozenset(invalid_strikes),
    )


def fetch_exact_contract_lookups(
    app: IbPortfolioApp,
    ticker: str,
    lookups: list[tuple[str, float]],
    right: str,
    *,
    timeout_seconds: float,
    deadline: float | None = None,
    stop_event: Event | None = None,
    concurrency: int = EXACT_CONTRACT_LOOKUP_CONCURRENCY,
    priority: ContractLookupPriority | None = None,
    slot_timeout_seconds: float | None = None,
) -> dict[tuple[str, float], list[ScannerOptionContract] | None]:
    """Resolve exact (expiration, strike) contracts; None marks a timeout."""
    if not lookups:
        return {}

    abort = Event()
    stop_signal = AnyEvent(stop_event, abort)

    def lookup(key: tuple[str, float]) -> list[ScannerOptionContract] | None:
        expiration, strike = key
        request_timeout = remaining_contract_timeout(timeout_seconds, deadline)
        if request_timeout <= 0 or stop_signal.is_set():
            return None
        try:
            return fetch_exact_option_contracts(
                app,
                ticker,
                expiration,
                strike,
                right,
                timeout_seconds=request_timeout,
                stop_event=stop_signal,
                priority=priority,
                slot_timeout_seconds=slot_timeout_seconds,
            )
        except OptionsDataUnavailable as error:
            if not is_contract_timeout(error):
                abort.set()
                raise
            if not stop_signal.is_set():
                logger.info(
                    "Exact option contract request timed out ticker=%s "
                    "expiration=%s strike=%s right=%s",
                    ticker,
                    expiration,
                    strike,
                    right,
                )
            return None
        except BaseException:
            abort.set()
            raise

    with ThreadPoolExecutor(
        max_workers=max(1, min(concurrency, len(lookups))),
        thread_name_prefix="ib-contract-lookup",
    ) as executor:
        futures = [executor.submit(lookup, key) for key in lookups]
        return {
            key: future.result() for key, future in zip(lookups, futures, strict=True)
        }


class AnyEvent:
    def __init__(self, *events: Event | None) -> None:
        self.events = [event for event in events if event is not None]

    def is_set(self) -> bool:
        return any(event.is_set() for event in self.events)


def fetch_exact_option_contracts(
    app: IbPortfolioApp,
    ticker: str,
    expiration: str,
    strike: float,
    right: str,
    *,
    timeout_seconds: float,
    stop_event: Event | AnyEvent | None = None,
    priority: ContractLookupPriority | None = None,
    slot_timeout_seconds: float | None = None,
) -> list[ScannerOptionContract]:
    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    remaining_seconds = send_contract_details_request(
        app,
        req_id,
        us_option_contract(
            ticker,
            expiration=expiration,
            strike=strike,
            right=right,
        ),
        timeout_seconds=timeout_seconds,
        stop_event=stop_event,
        priority=priority,
        slot_timeout_seconds=slot_timeout_seconds,
    )
    completed = wait_for_contract_details(ready, remaining_seconds, stop_event)
    with app.lock:
        details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)

    if pop_invalid_contract_error(app, req_id):
        return []
    if not completed:
        raise OptionsDataUnavailable(
            f"Option contract request timed out for {ticker} {expiration}."
        )

    return [
        scanner_contract(detail.contract)
        for detail in details
        if is_exact_standard_option_contract(
            detail.contract,
            ticker=ticker,
            expiration=expiration,
            strike=strike,
            right=right,
        )
    ]


def remaining_contract_timeout(
    timeout_seconds: float,
    deadline: float | None,
) -> float:
    if deadline is None:
        return timeout_seconds
    return min(timeout_seconds, max(0, deadline - monotonic()))


def send_contract_details_request(
    app: IbPortfolioApp,
    req_id: int,
    contract: Contract,
    *,
    timeout_seconds: float,
    stop_event: Event | AnyEvent | None = None,
    priority: ContractLookupPriority | None = None,
    urgent: bool = False,
    slot_timeout_seconds: float | None = None,
) -> float:
    """Send once a shared lookup slot frees; return the seconds left to wait.

    By default the slot wait counts against ``timeout_seconds``. With
    ``slot_timeout_seconds``, the slot wait has its own limit and IB gets the
    full ``timeout_seconds`` once the request is sent, so time queued behind
    this app's own lookups is not reported as an IB timeout.

    A request that never gets a slot is not sent and reports no time left,
    so callers treat it like a timeout and retry it later.
    """
    started_at = monotonic()
    if not contract_details_limiter(app).acquire(
        req_id,
        timeout=timeout_seconds if slot_timeout_seconds is None else slot_timeout_seconds,
        stop_event=stop_event,
        is_background=None if priority is None else priority.is_background,
        urgent=urgent,
    ):
        return 0.0
    app.reqContractDetails(req_id, contract)
    if slot_timeout_seconds is not None:
        return timeout_seconds
    return max(0.0, timeout_seconds - (monotonic() - started_at))


def wait_for_contract_details(
    ready: Event,
    timeout_seconds: float,
    stop_event: Event | AnyEvent | None,
) -> bool:
    deadline = monotonic() + max(0, timeout_seconds)
    while not ready.is_set():
        if stop_event is not None and stop_event.is_set():
            return False
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        ready.wait(timeout=min(remaining, 0.05))
    return True


def is_contract_timeout(error: OptionsDataUnavailable) -> bool:
    return "Option contract request timed out" in str(error)


def is_exact_standard_option_contract(
    contract: Contract,
    *,
    ticker: str,
    expiration: str,
    strike: float,
    right: str,
) -> bool:
    return (
        contract.secType == "OPT"
        and contract.symbol == ticker
        and contract.currency == "USD"
        and contract.right in {right, "PUT" if right == "P" else "CALL"}
        and contract.multiplier == "100"
        and contract.lastTradeDateOrContractMonth[:8]
        == expiration.replace("-", "")
        and contract.strike == strike
        and has_usable_trading_class(contract)
        and contract.conId > 0
        and bool(contract.localSymbol)
    )


def has_usable_trading_class(contract: Contract) -> bool:
    return bool(contract.tradingClass)


def select_refreshed_contract(
    contracts: list[ScannerOptionContract],
    *,
    con_id: int | None,
    local_symbol: str | None,
) -> ScannerOptionContract | None:
    if con_id is not None:
        matched_con_id = next(
            (contract for contract in contracts if contract.con_id == con_id),
            None,
        )
        if matched_con_id is not None:
            return matched_con_id
    if local_symbol:
        matched_local_symbol = next(
            (
                contract
                for contract in contracts
                if contract.local_symbol == local_symbol
            ),
            None,
        )
        if matched_local_symbol is not None:
            return matched_local_symbol
    return min(
        contracts,
        key=lambda contract: (
            0 if contract.exchange == "SMART" else 1,
            contract.con_id,
        ),
        default=None,
    )


def scanner_contract(contract: Contract) -> ScannerOptionContract:
    return ScannerOptionContract(
        con_id=contract.conId,
        ticker=contract.symbol,
        expiration=(
            f"{contract.lastTradeDateOrContractMonth[:4]}-"
            f"{contract.lastTradeDateOrContractMonth[4:6]}-"
            f"{contract.lastTradeDateOrContractMonth[6:8]}"
        ),
        strike=contract.strike,
        right=contract.right,
        exchange=contract.exchange or "SMART",
        currency=contract.currency,
        multiplier=contract.multiplier,
        trading_class=contract.tradingClass,
        local_symbol=contract.localSymbol,
    )


def scanner_market_data_contract(contract: ScannerOptionContract) -> Contract:
    ib_contract = Contract()
    ib_contract.conId = contract.con_id
    ib_contract.symbol = contract.ticker
    ib_contract.secType = "OPT"
    ib_contract.exchange = "SMART"
    ib_contract.currency = contract.currency
    ib_contract.lastTradeDateOrContractMonth = contract.expiration.replace("-", "")
    ib_contract.strike = contract.strike
    ib_contract.right = contract.right
    ib_contract.multiplier = contract.multiplier
    ib_contract.tradingClass = contract.trading_class
    ib_contract.localSymbol = contract.local_symbol
    return ib_contract


def option_right_code(right: str) -> str:
    return "C" if right == "CALL" else "P" if right == "PUT" else right


def clean_quote_value(value: float | int | None) -> float | None:
    if value is None:
        return None
    next_value = float(value)
    if abs(next_value) > 1e100:
        return None
    return next_value


class OptionMarketDataSubscriptions:
    def __init__(
        self,
        app: IbPortfolioApp,
        contracts: list[ScannerOptionContract],
        *,
        snapshot: bool,
    ) -> None:
        self.app = app
        self.contracts = contracts
        first_contract = contracts[0] if contracts else None
        self.ticker = first_contract.ticker if first_contract else ""
        self.expiration = first_contract.expiration if first_contract else ""
        self.snapshot = snapshot
        self.req_ids: list[int] = []
        # Set by ticks for this group only; see wait_for_quote_fields.
        self.ready = Event()
        self.pending_contracts = contracts
        self.contracts: list[ScannerOptionContract] = []

    def open(self) -> None:
        self.subscribe(self.pending_contracts)

    def subscribe(self, contracts: list[ScannerOptionContract]) -> None:
        if not contracts:
            return
        started_at = perf_counter()
        requests = []
        if not self.ticker:
            self.ticker = contracts[0].ticker
            self.expiration = contracts[0].expiration
        with self.app.lock:
            for contract in contracts:
                req_id = self.app.next_option_market_req_id
                self.app.next_option_market_req_id += 1
                option_key = (contract.strike, option_right_code(contract.right))
                self.app.option_market_req_to_key[req_id] = option_key
                self.app.option_market_data[req_id] = {
                    "local_symbol": contract.local_symbol,
                }
                self.app.option_market_ready_by_req_id[req_id] = self.ready
                self.req_ids.append(req_id)
                requests.append(
                    (
                        req_id,
                        scanner_market_data_contract(contract),
                        OPTION_MARKET_DATA_GENERIC_TICKS,
                        self.snapshot,
                        False,
                        [],
                    )
                )

        for request in requests:
            self.app.reqMktData(*request)

        self.contracts.extend(contracts)
        line_usage = market_data_line_usage(self.app)
        logger.info(
            "Option chain market-data subscriptions opened ticker=%s "
            "expiration=%s strikes=%s subscriptions=%s active_lines=%s "
            "peak_lines=%s open_ms=%.1f",
            self.ticker,
            self.expiration,
            len({contract.strike for contract in contracts}),
            len(requests),
            line_usage[0] if line_usage else None,
            line_usage[1] if line_usage else None,
            elapsed_ms(started_at),
        )

    def keys(self) -> list[tuple[float, str]]:
        return [option_contract_key(contract) for contract in self.contracts]

    def unsubscribe_except(self, contracts: list[ScannerOptionContract]) -> int:
        """Cancel subscriptions not in contracts; return how many were cancelled."""
        keep = {option_contract_key(contract) for contract in contracts}
        kept = [
            (req_id, contract)
            for req_id, contract in zip(self.req_ids, self.contracts)
            if option_contract_key(contract) in keep
        ]
        removed = [
            req_id
            for req_id, contract in zip(self.req_ids, self.contracts)
            if option_contract_key(contract) not in keep
        ]
        if not removed:
            return 0
        self.req_ids = [req_id for req_id, _contract in kept]
        self.contracts = [contract for _req_id, contract in kept]
        with self.app.lock:
            for req_id in removed:
                self.app.option_market_ready_by_req_id.pop(req_id, None)
                self.app.option_market_req_to_key.pop(req_id, None)
                self.app.option_market_data.pop(req_id, None)
        for req_id in removed:
            self.app.cancelMktData(req_id)
        forget_limit_errors(self.app, removed)
        return len(removed)

    def snapshot_values(self) -> dict[tuple[float, str], dict[str, float | int | None]]:
        with self.app.lock:
            return {
                self.app.option_market_req_to_key[req_id]: self.app.option_market_data[
                    req_id
                ].copy()
                for req_id in self.req_ids
                if req_id in self.app.option_market_req_to_key
                and req_id in self.app.option_market_data
            }

    def changed_values(
        self,
        latest_values: dict[tuple[float, str], dict[str, float | int | None]],
    ) -> Iterable[tuple[tuple[float, str], dict[str, float | int | None]]]:
        with self.app.lock:
            self.ready.clear()

            for req_id in self.req_ids:
                key = self.app.option_market_req_to_key.get(req_id)
                values = self.app.option_market_data.get(req_id)
                if key is None or values is None:
                    continue

                current_values = values.copy()
                if latest_values.get(key) == current_values:
                    continue

                yield key, current_values

    def close(self) -> None:
        started_at = perf_counter()
        with self.app.lock:
            req_ids_to_cancel = list(self.req_ids)
            for req_id in self.req_ids:
                self.app.option_market_ready_by_req_id.pop(req_id, None)
                option_key = self.app.option_market_req_to_key.pop(req_id, None)
                if option_key is not None:
                    self.app.option_market_data.pop(req_id, None)

        for req_id in req_ids_to_cancel:
            self.app.cancelMktData(req_id)

        logger.info(
            "Option chain market-data subscriptions closed ticker=%s "
            "expiration=%s subscriptions=%s request_errors=%s limit_errors=%s "
            "close_ms=%.1f",
            self.ticker,
            self.expiration,
            len(req_ids_to_cancel),
            self.request_error_count(req_ids_to_cancel),
            limit_error_counts(self.app, req_ids_to_cancel),
            elapsed_ms(started_at),
        )
        forget_limit_errors(self.app, req_ids_to_cancel)

    def line_limited_count(self) -> int:
        return len(line_limited_req_ids(self.app, self.req_ids))

    def request_error_count(self, req_ids: list[int]) -> int:
        request_errors = getattr(self.app, "request_errors_by_req_id", None)
        if request_errors is None:
            return 0

        with self.app.lock:
            return sum(1 for req_id in req_ids if req_id in request_errors)


def wait_for_quote_fields(
    app,
    req_ids: list[int],
    ready: Event,
    *,
    max_wait_seconds: float,
    settle_seconds: float = QUOTE_SETTLE_SECONDS,
    cancel_event: Event | None = None,
    started_at: float,
) -> tuple[str | None, str | None, str | None]:
    """Wait until every quote has bid, ask, and delta, or until every quote
    has delta and one side and no new field arrives for `settle_seconds`.
    Anything less, such as contracts that never quote, ends the wait at
    `max_wait_seconds`."""
    deadline = monotonic() + max(0, max_wait_seconds)
    settle_deadline = None
    present_fields = 0
    first_data_ms = None
    complete_ms = None
    last_change_ms = None
    while True:
        ready.clear()
        limited = line_limited_req_ids(app, req_ids)
        with app.lock:
            presence = [
                [
                    clean_quote_value(
                        app.option_market_data.get(req_id, {}).get(field)
                    )
                    is not None
                    for field in QUOTE_FIELDS
                ]
                for req_id in req_ids
                if req_id not in limited
            ]
        now = monotonic()
        next_present_fields = sum(sum(fields) for fields in presence)
        if next_present_fields != present_fields:
            present_fields = next_present_fields
            last_change_ms = elapsed_ms(started_at)
            first_data_ms = first_data_ms or last_change_ms
            settle_deadline = now + settle_seconds
        if present_fields == len(presence) * len(QUOTE_FIELDS):
            complete_ms = elapsed_ms(started_at)
            break
        # IB spreads a batch's first ticks over seconds with pauses longer
        # than the settle interval; only a missing bid is common enough on
        # far strikes to stop waiting for early.
        settleable = all(
            has_delta and (has_bid or has_ask)
            for has_bid, has_ask, has_delta in presence
        )
        wait_until = (
            min(deadline, settle_deadline or deadline) if settleable else deadline
        )
        if now >= wait_until or (cancel_event is not None and cancel_event.is_set()):
            break
        ready.wait(min(wait_until - now, 0.05))
    return tuple(
        f"{value:.0f}" if value is not None else None
        for value in (first_data_ms, complete_ms, last_change_ms)
    )


def option_contract_key(contract: ScannerOptionContract) -> tuple[float, str]:
    return (contract.strike, option_right_code(contract.right))


def elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1_000


def market_data_line_usage(app) -> tuple[int, int] | None:
    line_usage = getattr(app, "market_data_line_usage", None)
    return line_usage() if line_usage is not None else None


def limit_error_counts(app, req_ids: Iterable[int]) -> dict[int, int]:
    error_counts = getattr(app, "limit_error_count", None)
    return error_counts(req_ids) if error_counts is not None else {}


def missing_quote_field_counts(
    values_by_req_id: dict[int, dict[str, float | int | None]],
) -> dict[str, int]:
    return {
        field: sum(
            1
            for values in values_by_req_id.values()
            if clean_quote_value(values.get(field)) is None
        )
        for field in ("bid", "ask", "delta")
    }


def line_limited_req_ids(app, req_ids: Iterable[int]) -> set[int]:
    limit_errors = getattr(app, "limit_errors_by_req_id", None)
    if limit_errors is None:
        return set()
    with app.lock:
        return {
            req_id
            for req_id in req_ids
            if limit_errors.get(req_id) == IB_MARKET_DATA_LINE_LIMIT_CODE
        }


def forget_limit_errors(app, req_ids: Iterable[int]) -> None:
    limit_errors = getattr(app, "limit_errors_by_req_id", None)
    if limit_errors is None:
        return
    with app.lock:
        for req_id in req_ids:
            limit_errors.pop(req_id, None)


def chain_stream_warning(
    total_contracts: int,
    subscribed_contracts: int,
    line_limited_contracts: int,
) -> str | None:
    if line_limited_contracts:
        return (
            f"IB rejected {line_limited_contracts} contract(s) at the "
            "market-data line limit; their quotes stay blank."
        )
    if subscribed_contracts < total_contracts:
        return (
            "Waiting for free IB market-data lines: streaming "
            f"{subscribed_contracts} of {total_contracts} contract(s)."
        )
    return None
