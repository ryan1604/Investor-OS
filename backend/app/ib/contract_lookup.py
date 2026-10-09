from __future__ import annotations


from concurrent.futures import ThreadPoolExecutor
import logging
from threading import Event
from time import monotonic

from ibapi.contract import Contract

from app.ib.app import IB_INVALID_CONTRACT_CODES, IbPortfolioApp
from app.ib.contracts import us_option_contract, us_option_universe_contract
from app.ib.pacing import contract_details_limiter
from app.options.types import (
    ContractLookupPriority,
    OptionChainContractHydration,
    OptionsDataUnavailable,
    ScannerContractSelection,
    ScannerOptionContract,
)

EXACT_CONTRACT_LOOKUP_CONCURRENCY = 10
# Longest wait for a shared contract-details slot when the slot wait has its
# own limit; matches the limiter's stale-slot reclaim, so a slot always frees.
CONTRACT_DETAILS_SLOT_WAIT_SECONDS = 60
logger = logging.getLogger(__name__)


def raise_invalid_ticker_if_needed(app, req_id: int, ticker: str) -> None:
    request_errors = app.request_errors_by_req_id

    with app.lock:
        request_error = request_errors.pop(req_id, None)

    if request_error and request_error[0] in IB_INVALID_CONTRACT_CODES:
        raise OptionsDataUnavailable(f"Invalid ticker: {ticker}.")


def pop_invalid_contract_error(app, req_id: int) -> bool:
    request_errors = app.request_errors_by_req_id

    with app.lock:
        request_error = request_errors.pop(req_id, None)

    return bool(request_error and request_error[0] in IB_INVALID_CONTRACT_CODES)


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
        and bool(contract.tradingClass)
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
    (only_right,) = strikes_by_right if len(strikes_by_right) == 1 else ("",)
    req_id, details, completed = request_contract_details(
        app,
        us_option_universe_contract(
            ticker,
            expiration=expiration,
            right=only_right,
        ),
        timeout_seconds=timeout_seconds,
        stop_event=stop_event,
        priority=priority,
    )

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
    req_id, details, completed = request_contract_details(
        app,
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


def request_contract_details(
    app: IbPortfolioApp,
    contract: Contract,
    *,
    timeout_seconds: float,
    stop_event: Event | AnyEvent | None = None,
    priority: ContractLookupPriority | None = None,
    urgent: bool = False,
    slot_timeout_seconds: float | None = None,
) -> tuple[int, list, bool]:
    """Send one contract-details request and wait for IB to finish it.

    Returns the request id, the details received, and whether IB finished
    before the timeout or stop event.
    """
    with app.lock:
        req_id = app.next_contract_details_req_id
        app.next_contract_details_req_id += 1
        app.contract_details[req_id] = []
        ready = Event()
        app.contract_details_ready_by_req_id[req_id] = ready

    remaining_seconds = send_contract_details_request(
        app,
        req_id,
        contract,
        timeout_seconds=timeout_seconds,
        stop_event=stop_event,
        priority=priority,
        urgent=urgent,
        slot_timeout_seconds=slot_timeout_seconds,
    )
    completed = wait_for_contract_details(ready, remaining_seconds, stop_event)
    with app.lock:
        details = app.contract_details.pop(req_id, [])
        app.contract_details_ready_by_req_id.pop(req_id, None)
    return req_id, details, completed


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
    return is_standard_option_contract(
        contract,
        ticker=ticker,
        expiration=expiration,
        allowed_strikes={strike},
        right=right,
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
