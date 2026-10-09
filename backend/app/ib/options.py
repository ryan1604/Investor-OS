from __future__ import annotations


from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import logging
from queue import Empty, SimpleQueue
from threading import Event, Lock, Thread
from time import monotonic, perf_counter

from app.ib.app import IbPortfolioApp
from app.ib.contract_lookup import (
    CONTRACT_DETAILS_SLOT_WAIT_SECONDS,
    AnyEvent,
    fetch_exact_chain_contract_hydration,
    fetch_standard_option_contracts,
    is_contract_timeout,
    raise_invalid_ticker_if_needed,
    remaining_contract_timeout,
    request_contract_details,
)
from app.ib.contracts import option_right_code, us_equity_contract
from app.ib.market_data_lines import market_data_line_budget
from app.ib.option_quotes import (
    OptionMarketDataSubscriptions,
    option_contract_key,
    wait_for_quote_fields,
)
from app.options.domain import (
    current_us_market_date,
    OptionMetadata,
    to_option_quote,
)
from app.options.rotation import OptionChainRotation
from app.options.types import (
    ContractLookupPriority,
    OptionChainContractHydration,
    OptionChainStreamNotice,
    OptionsDataUnavailable,
    ScannerOptionContract,
)
from app.schemas import OptionQuote
from app.tickers import normalize_ticker
from app.timing import elapsed_ms

OPTION_RIGHTS = ("C", "P")
logger = logging.getLogger(__name__)


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

        contract_req_id, contract_details, contract_details_completed = (
            request_contract_details(
                self.app,
                contract,
                timeout_seconds=self.timeout_seconds,
                urgent=True,
                slot_timeout_seconds=CONTRACT_DETAILS_SLOT_WAIT_SECONDS,
            )
        )

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
