from __future__ import annotations


import logging
from threading import Event, Lock
from time import monotonic, perf_counter

from app.ib.app import IbPortfolioApp
from app.ib.contract_lookup import (
    CONTRACT_DETAILS_SLOT_WAIT_SECONDS,
    fetch_exact_contract_lookups,
    is_exact_standard_option_contract,
    raise_invalid_ticker_if_needed,
    scanner_contract,
    request_contract_details,
)
from app.ib.contracts import clean_ib_float, us_option_contract
from app.ib.market_data_lines import market_data_line_budget
from app.ib.option_quotes import (
    OPTION_MARKET_DATA_GENERIC_TICKS,
    QUOTE_FIELDS,
    QUOTE_SETTLE_SECONDS,
    forget_limit_errors,
    limit_error_counts,
    line_limited_req_ids,
    market_data_line_usage,
    scanner_market_data_contract,
    wait_for_quote_fields,
)
from app.options.types import (
    OptionsDataUnavailable,
    ScannerContractSelection,
    ScannerOptionContract,
    ScannerOptionQuote,
)
from app.tickers import normalize_ticker
from app.timing import elapsed_ms

logger = logging.getLogger(__name__)


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
            value is not None and clean_ib_float(float(value)) is not None
            for value in (values.get(field) for field in QUOTE_FIELDS)
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
        subscriptions = [
            ScannerQuoteSubscription(index, contract) for index, contract in pending
        ]
        requests = self._register_quote_requests(
            [contract for _index, contract in pending],
            ready,
        )
        active.update(zip((request[0] for request in requests), subscriptions))
        for request in requests:
            self.app.reqMktData(*request)

    def _register_quote_requests(
        self,
        contracts: list[ScannerOptionContract],
        ready: Event,
    ) -> list[tuple]:
        """Register streaming quote requests; return their reqMktData arguments."""
        requests = []
        with self.app.lock:
            for contract in contracts:
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
        with self.active_req_ids_lock:
            self.active_req_ids.update(request[0] for request in requests)
        return requests

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
        req_id, details, completed = request_contract_details(
            self.app,
            us_option_contract(
                ticker,
                expiration=expiration,
                strike=strike,
                right=right,
            ),
            timeout_seconds=self.contract_timeout_seconds,
            urgent=True,
        )

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
        ready = Event()
        requests = self._register_quote_requests(contracts, ready)
        req_ids = {
            request[0]: contract for request, contract in zip(requests, contracts)
        }
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
        bid=(
            clean_ib_float(float(values["bid"]))
            if values.get("bid") is not None
            else None
        ),
        ask=(
            clean_ib_float(float(values["ask"]))
            if values.get("ask") is not None
            else None
        ),
        delta=(
            clean_ib_float(float(values["delta"]))
            if values.get("delta") is not None
            else None
        ),
        line_limited=line_limited,
    )


def percentile_ms(sorted_values: list[float], fraction: float) -> str | None:
    if not sorted_values:
        return None
    return f"{sorted_values[int(fraction * (len(sorted_values) - 1))]:.0f}"


def missing_quote_field_counts(
    values_by_req_id: dict[int, dict[str, float | int | None]],
) -> dict[str, int]:
    return {
        field: sum(
            value is None or clean_ib_float(float(value)) is None
            for value in (
                values.get(field) for values in values_by_req_id.values()
            )
        )
        for field in ("bid", "ask", "delta")
    }


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
