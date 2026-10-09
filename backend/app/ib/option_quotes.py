from __future__ import annotations


from collections.abc import Iterable
import logging
from threading import Event
from time import monotonic, perf_counter

from ibapi.contract import Contract

from app.ib.app import IB_MARKET_DATA_LINE_LIMIT_CODE, IbPortfolioApp
from app.ib.contracts import clean_ib_float, option_right_code
from app.options.types import ScannerOptionContract
from app.timing import elapsed_ms

OPTION_MARKET_DATA_GENERIC_TICKS = "100,101,104,106"
QUOTE_FIELDS = ("bid", "ask", "delta")
QUOTE_SETTLE_SECONDS = 0.3
logger = logging.getLogger(__name__)


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
        request_errors = self.app.request_errors_by_req_id

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
                    value is not None and clean_ib_float(float(value)) is not None
                    for value in (
                        app.option_market_data.get(req_id, {}).get(field)
                        for field in QUOTE_FIELDS
                    )
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


def market_data_line_usage(app) -> tuple[int, int] | None:
    return app.market_data_line_usage()


def limit_error_counts(app, req_ids: Iterable[int]) -> dict[int, int]:
    return app.limit_error_count(req_ids)


def line_limited_req_ids(app, req_ids: Iterable[int]) -> set[int]:
    limit_errors = app.limit_errors_by_req_id
    with app.lock:
        return {
            req_id
            for req_id in req_ids
            if limit_errors.get(req_id) == IB_MARKET_DATA_LINE_LIMIT_CODE
        }


def forget_limit_errors(app, req_ids: Iterable[int]) -> None:
    limit_errors = app.limit_errors_by_req_id
    with app.lock:
        for req_id in req_ids:
            limit_errors.pop(req_id, None)
