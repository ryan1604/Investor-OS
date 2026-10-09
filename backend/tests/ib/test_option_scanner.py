import threading
from time import perf_counter

from app.ib.contract_lookup import EXACT_CONTRACT_LOOKUP_CONCURRENCY
from app.ib.option_scanner import IbOptionScannerProvider
from app.options.types import ScannerOptionContract
from tests.ib.fakes import (
    AllContractDetailsTimeoutOptionChainIbApp,
    FakeOptionChainIbApp,
    SharedSlotExactOptionChainIbApp,
    TimeoutBroadOptionChainIbApp,
)


class DelayedExactOptionChainIbApp(TimeoutBroadOptionChainIbApp):
    def __init__(self, contract_strikes: list[float]) -> None:
        super().__init__(contract_strikes=contract_strikes)
        self.in_flight = 0
        self.max_in_flight = 0

    def reqContractDetails(self, req_id, contract) -> None:
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)

        def respond() -> None:
            with self.lock:
                self.in_flight -= 1
            TimeoutBroadOptionChainIbApp.reqContractDetails(self, req_id, contract)

        threading.Timer(0.02, respond).start()


def test_ib_scanner_provider_resolves_exact_contracts_without_broad_request():
    app = TimeoutBroadOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionScannerProvider(app, contract_timeout_seconds=0.01)

    selection = provider.fetch_option_contracts(
        "hims",
        [("2026-07-31", 95), ("2026-07-31", 100), ("2026-07-31", 105)],
        "P",
        threading.Event(),
    )

    assert {contract.strike for contract in selection.contracts} == {95, 100}
    assert all(request[1].strike > 0 for request in app.contract_detail_requests)
    assert selection.excluded_contracts == 1
    assert selection.invalid_lookups == frozenset({("2026-07-31", 105)})
    assert selection.timed_out_lookups == frozenset()


def test_ib_scanner_resolves_exact_contracts_concurrently_in_strike_order():
    app = DelayedExactOptionChainIbApp(
        contract_strikes=[strike for strike in range(90, 110) if strike % 3]
    )
    provider = IbOptionScannerProvider(app, contract_timeout_seconds=1)
    expirations = ["2026-07-24", "2026-07-31"]
    strikes = list(range(90, 110))

    selection = provider.fetch_option_contracts(
        "hims",
        [(expiration, strike) for expiration in expirations for strike in strikes],
        "P",
        threading.Event(),
    )

    assert [
        (contract.expiration, contract.strike) for contract in selection.contracts
    ] == [
        (expiration, strike)
        for expiration in expirations
        for strike in strikes
        if strike % 3
    ]
    assert selection.excluded_contracts == 2 * len(
        [strike for strike in strikes if not strike % 3]
    )
    assert 1 < app.max_in_flight <= EXACT_CONTRACT_LOOKUP_CONCURRENCY


def test_ib_scanner_lookups_queued_for_shared_slots_are_not_timed_out():
    # One slot answered in 10 ms serializes 20 lookups for about 200 ms, far
    # past the 50 ms IB timeout; queued time must not drop strikes.
    strikes = list(range(90, 110))
    app = SharedSlotExactOptionChainIbApp(contract_strikes=strikes, slots=1)
    provider = IbOptionScannerProvider(app, contract_timeout_seconds=0.05)

    selection = provider.fetch_option_contracts(
        "hims",
        [("2026-07-31", strike) for strike in strikes],
        "P",
        threading.Event(),
    )

    assert [contract.strike for contract in selection.contracts] == strikes
    assert selection.timed_out_lookups == frozenset()


def test_ib_scanner_cancellation_stops_outstanding_contract_lookups():
    app = AllContractDetailsTimeoutOptionChainIbApp()
    provider = IbOptionScannerProvider(app, contract_timeout_seconds=5)
    cancel_event = threading.Event()
    threading.Timer(0.05, cancel_event.set).start()
    strikes = list(range(1, 51))

    started_at = perf_counter()
    selection = provider.fetch_option_contracts(
        "hims",
        [("2026-07-31", strike) for strike in strikes],
        "P",
        cancel_event,
    )
    elapsed = perf_counter() - started_at

    assert elapsed < 1
    assert selection.contracts == []
    assert selection.excluded_contracts == len(strikes)
    assert len(selection.timed_out_lookups) == len(strikes)
    assert len(app.contract_detail_requests) <= EXACT_CONTRACT_LOOKUP_CONCURRENCY


def test_scanner_quote_batch_returns_before_the_maximum_wait():
    app = FakeOptionChainIbApp()
    app.reqMarketDataType = lambda _market_data_type: None
    provider = IbOptionScannerProvider(app, quote_wait_seconds=4)
    contract = ScannerOptionContract(
        con_id=1,
        ticker="AAPL",
        expiration="2026-06-19",
        strike=100,
        right="P",
        exchange="SMART",
        currency="USD",
        multiplier="100",
        trading_class="AAPL",
        local_symbol="AAPL1P",
    )
    started_at = perf_counter()

    quotes = provider.fetch_quotes([contract], threading.Event())

    assert perf_counter() - started_at < 1
    assert [(quote.bid, quote.ask, quote.delta) for quote in quotes] == [
        (1, 1.4, 0.5)
    ]
    assert app.option_market_ready_by_req_id == {}