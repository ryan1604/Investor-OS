import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from time import perf_counter

import pytest

from app.ib.market_data_lines import MarketDataLineBudget
from app.ib.contracts import us_equity_contract
from app.ib.contract_lookup import EXACT_CONTRACT_LOOKUP_CONCURRENCY
from app.ib.options import (
    IbOptionChainSnapshotProvider,
    IbOptionChainStreamProvider,
    IbOptionMetadataProvider,
)
from app.options.client import CachedOptionMetadataProvider
from app.options.types import (
    OptionChainStreamNotice,
    OptionsDataUnavailable,
    ScannerOptionContract,
)
from app.options.rotation import (
    OptionChainRotation,
    preferred_chain_contracts,
)
from app.options.domain import OptionMetadata
from app.schemas import OptionQuote
from tests.conftest import FakeIbAppBase, wait_until
from tests.ib.fakes import (
    AllContractDetailsTimeoutOptionChainIbApp,
    FakeOptionChainIbApp,
    TimeoutBroadOptionChainIbApp,
    deliver_ticks_later,
    fake_option_contract,
    requested_rights,
)


def test_us_equity_contract_uses_stock_smart_usd_contract_shape():
    contract = us_equity_contract("sofi")

    assert contract.symbol == "SOFI"
    assert contract.secType == "STK"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"


class FakeContractDetails:
    def __init__(self, con_id: int) -> None:
        contract = us_equity_contract("AAPL")
        contract.conId = con_id
        self.contract = contract


class FakeOptionMetadataIbApp(FakeIbAppBase):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.next_contract_details_req_id = 70_000
        self.next_option_params_req_id = 80_000
        self.contract_details = {}
        self.option_metadata: dict[int, OptionMetadata] = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.option_metadata_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.contract_detail_requests = []
        self.option_parameter_requests = []
        self.market_data_requests = []

    def isConnected(self) -> bool:
        return True

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [FakeContractDetails(12345)]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqSecDefOptParams(
        self,
        req_id,
        underlying_symbol,
        fut_fop_exchange,
        underlying_sec_type,
        underlying_con_id,
    ) -> None:
        self.option_parameter_requests.append(
            (
                req_id,
                underlying_symbol,
                fut_fop_exchange,
                underlying_sec_type,
                underlying_con_id,
            )
        )
        self.option_metadata[req_id] = OptionMetadata(
            expirations=["2026-07-17", "2026-06-19"],
            strikes=[95, 100, 105],
        )
        self.option_metadata_ready_by_req_id[req_id].set()

    def reqMktData(self, *args) -> None:
        self.market_data_requests.append(args)


def test_ib_option_metadata_provider_fetches_metadata_without_market_quotes():
    app = FakeOptionMetadataIbApp()
    provider = IbOptionMetadataProvider(app)

    metadata = provider.fetch_option_metadata("aapl")

    requested_contract = app.contract_detail_requests[0][1]
    assert requested_contract.symbol == "AAPL"
    assert requested_contract.secType == "STK"
    assert requested_contract.exchange == "SMART"
    assert requested_contract.currency == "USD"
    assert app.option_parameter_requests == [
        (80_000, "AAPL", "", "STK", 12345),
    ]
    assert metadata.expirations == ["2026-07-17", "2026-06-19"]
    assert metadata.strikes == [95, 100, 105]
    assert app.market_data_requests == []


class DisconnectedOptionMetadataIbApp(FakeOptionMetadataIbApp):
    def isConnected(self) -> bool:
        return False


class RecoveringOptionMetadataIbApp(FakeOptionMetadataIbApp):
    def __init__(self) -> None:
        super().__init__()
        self.should_respond = False

    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        if self.should_respond:
            self.contract_details[req_id] = [FakeContractDetails(12345)]
            self.contract_details_ready_by_req_id[req_id].set()


def test_ib_option_metadata_provider_rejects_disconnected_ib_without_caching():
    cache = CachedOptionMetadataProvider(
        IbOptionMetadataProvider(DisconnectedOptionMetadataIbApp())
    )

    try:
        cache.fetch_option_metadata("AAPL")
    except OptionsDataUnavailable as error:
        assert str(error) == (
            "Options metadata is unavailable while IB is disconnected."
        )
    else:
        raise AssertionError("Expected disconnected metadata request to fail.")

    assert cache.entries == {}


def test_ib_option_metadata_timeout_is_not_cached_and_retry_recovers():
    app = RecoveringOptionMetadataIbApp()
    cache = CachedOptionMetadataProvider(
        IbOptionMetadataProvider(app, timeout_seconds=0.01)
    )

    try:
        cache.fetch_option_metadata("AAPL")
    except OptionsDataUnavailable as error:
        assert str(error) == "Options metadata request timed out for AAPL."
    else:
        raise AssertionError("Expected metadata timeout.")

    app.should_respond = True
    metadata = cache.fetch_option_metadata("AAPL")

    assert metadata.strikes == [95, 100, 105]
    assert len(app.contract_detail_requests) == 2
    assert cache.entries["AAPL"].metadata == metadata


class SlowOptionChainIbApp(FakeOptionChainIbApp):
    def reqMktData(
        self,
        req_id,
        contract,
        generic_tick_list,
        snapshot,
        regulatory_snapshot,
        mkt_data_options,
    ) -> None:
        self.market_data_requests.append(
            (
                req_id,
                contract,
                generic_tick_list,
                snapshot,
                regulatory_snapshot,
                mkt_data_options,
            )
        )
        self.option_market_data[req_id] = {"open_interest": 100}
        self.signal_option_market_data(req_id)

        def add_prices() -> None:
            with self.lock:
                self.option_market_data[req_id].update({"bid": 1, "ask": 1.4})
                self.signal_option_market_data(req_id)

        threading.Timer(0.02, add_prices).start()


class SlowContractDetailsOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))

        def add_details() -> None:
            self.contract_details[req_id] = [
                type(
                    "ContractDetails",
                    (),
                    {
                        "contract": fake_option_contract(
                            contract,
                            100,
                            con_id=req_id + 10_000,
                            right=right,
                        )
                    },
                )()
                for right in requested_rights(contract)
            ]
            self.contract_details_ready_by_req_id[req_id].set()

        threading.Timer(0.02, add_details).start()


class RecoveringExactTimeoutOptionChainIbApp(TimeoutBroadOptionChainIbApp):
    def __init__(self) -> None:
        super().__init__(contract_strikes=[95, 100])
        self.exact_attempts: dict[tuple[float, str], int] = {}

    def reqContractDetails(self, req_id, contract) -> None:
        if contract.strike == 0:
            self.contract_detail_requests.append((req_id, contract))
            return

        key = (contract.strike, contract.right)
        self.exact_attempts[key] = self.exact_attempts.get(key, 0) + 1
        if contract.strike == 100 and self.exact_attempts[key] == 1:
            self.contract_detail_requests.append((req_id, contract))
            return

        super().reqContractDetails(req_id, contract)


class InvalidExactOptionChainIbApp(TimeoutBroadOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        if contract.strike == 0:
            return

        if contract.strike not in self.contract_strikes:
            self.request_errors_by_req_id[req_id] = (200, "No security definition")
            self.contract_details_ready_by_req_id[req_id].set()
            return

        self.contract_details[req_id] = [
            type(
                "ContractDetails",
                (),
                {
                    "contract": fake_option_contract(
                        contract,
                        contract.strike,
                        con_id=req_id + int(contract.strike * 100),
                    )
                },
            )()
        ]
        self.contract_details_ready_by_req_id[req_id].set()


class InvalidBroadOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.request_errors_by_req_id[req_id] = (200, "No security definition")
        self.contract_details_ready_by_req_id[req_id].set()


class EtfOptionChainIbApp(FakeOptionChainIbApp):
    def reqContractDetails(self, req_id, contract) -> None:
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": option_contract})()
            for right in requested_rights(contract)
            for index, strike in enumerate(self.contract_strikes)
            for option_contract in [
                fake_option_contract(
                    contract,
                    strike,
                    con_id=req_id + index + int(strike * 100),
                    trading_class=f"{contract.symbol}1",
                    right=right,
                )
            ]
        ]
        self.contract_details_ready_by_req_id[req_id].set()


def test_ib_chain_provider_quotes_only_requested_expiration_and_strikes():
    app = FakeOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(app)

    contracts = preferred_chain_contracts(provider.fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [95, 100],
    ).contracts)
    quotes = provider.fetch_chain_quotes(contracts)

    requested_contracts = [request[1] for request in app.market_data_requests]
    assert len(app.contract_detail_requests) == 1
    assert len(requested_contracts) == 4
    assert {contract.conId for contract in requested_contracts}
    assert {contract.lastTradeDateOrContractMonth for contract in requested_contracts} == {
        "20260619",
    }
    assert {contract.strike for contract in requested_contracts} == {95, 100}
    assert {contract.right for contract in requested_contracts} == {"C", "P"}
    assert all(contract.symbol == "AAPL" for contract in requested_contracts)
    assert all(contract.secType == "OPT" for contract in requested_contracts)
    assert all(request[3] is False for request in app.market_data_requests)
    assert app.cancelled_market_data == [90_000, 90_001, 90_002, 90_003]
    assert app.ib_calls_inside_lock == []
    assert quotes[(95, "C")].mid == 1.2
    assert quotes[(95, "C")].breakeven == 96.4


def test_ib_chain_provider_keeps_etf_contracts_with_class_aliases():
    app = EtfOptionChainIbApp(contract_strikes=[710, 711, 712])
    provider = IbOptionChainSnapshotProvider(app)

    contracts = preferred_chain_contracts(provider.fetch_chain_contract_hydration(
        "qqq",
        "2026-06-29",
        [710, 711, 712],
    ).contracts)

    assert {contract.strike for contract in contracts} == {710, 711, 712}
    assert {contract.right for contract in contracts} == {"C", "P"}
    assert {contract.trading_class for contract in contracts} == {"QQQ1"}


def test_ib_chain_provider_uses_separate_contract_timeout():
    app = SlowContractDetailsOptionChainIbApp(contract_strikes=[100])
    provider = IbOptionChainSnapshotProvider(
        app,
        timeout_seconds=0.01,
        contract_timeout_seconds=0.05,
    )

    contracts = preferred_chain_contracts(provider.fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [100],
    ).contracts)
    quotes = provider.fetch_chain_quotes(contracts)

    assert {contract.right for contract in contracts} == {"C", "P"}
    assert set(quotes) == {(100, "C"), (100, "P")}


def test_ib_chain_provider_falls_back_to_exact_contracts_after_broad_timeout():
    app = TimeoutBroadOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.01,
    )

    contracts = preferred_chain_contracts(provider.fetch_chain_contract_hydration(
        "hims",
        "2026-07-31",
        [95, 100, 105],
    ).contracts)
    quotes = provider.fetch_chain_quotes(contracts)

    assert {contract.strike for contract in contracts} == {95, 100}
    assert {request[1].strike for request in app.market_data_requests} == {95, 100}
    assert set(quotes) == {
        (95, "C"),
        (95, "P"),
        (100, "C"),
        (100, "P"),
    }


def test_ib_chain_provider_bounds_aggregate_contract_hydration_time():
    app = AllContractDetailsTimeoutOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.02,
        hydration_timeout_seconds=0.07,
    )
    strikes = list(range(1, 101))

    started_at = perf_counter()
    hydration = provider.fetch_chain_contract_hydration(
        "hims",
        "2026-07-31",
        strikes,
    )
    elapsed = perf_counter() - started_at

    assert elapsed < 0.5
    assert hydration.contracts == []
    assert hydration.timed_out_strikes == frozenset(strikes)
    # Each right sends one broad request, then at most four rounds of
    # concurrent exact lookups fit before the shared deadline.
    assert len(app.contract_detail_requests) <= 2 * (
        1 + EXACT_CONTRACT_LOOKUP_CONCURRENCY * 4
    )


def test_ib_chain_provider_honors_cancellation_during_contract_wait():
    app = AllContractDetailsTimeoutOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=1,
        hydration_timeout_seconds=10,
    )
    stop_event = threading.Event()

    with ThreadPoolExecutor(max_workers=1) as executor:
        hydration_future = executor.submit(
            provider.fetch_chain_contract_hydration,
            "hims",
            "2026-07-31",
            [95, 100],
            stop_event,
        )
        # One broad request covers calls and puts.
        wait_until(lambda: len(app.contract_detail_requests) == 1)
        stop_event.set()
        hydration = hydration_future.result(timeout=0.5)

    assert hydration.contracts == []
    assert hydration.timed_out_strikes == frozenset({95, 100})
    assert len(app.contract_detail_requests) == 1


def test_ib_chain_provider_distinguishes_timed_out_and_invalid_strikes():
    app = RecoveringExactTimeoutOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.01,
    )

    first_hydration = provider.fetch_chain_contract_hydration(
        "hims",
        "2026-07-31",
        [95, 100, 105],
    )
    retry_hydration = provider.fetch_chain_contract_hydration(
        "hims",
        "2026-07-31",
        [100],
    )

    assert {contract.strike for contract in first_hydration.contracts} == {95}
    assert first_hydration.timed_out_strikes == frozenset({100})
    assert first_hydration.invalid_strikes == frozenset({105})
    assert {contract.strike for contract in retry_hydration.contracts} == {100}
    assert retry_hydration.timed_out_strikes == frozenset()
    assert retry_hydration.invalid_strikes == frozenset()


def test_ib_chain_fallback_resolves_nearest_strikes_for_both_rights():
    app = TimeoutBroadOptionChainIbApp(contract_strikes=list(range(80, 121)))
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.05,
    )

    hydration = provider.fetch_chain_contract_hydration(
        "hims",
        "2026-07-31",
        list(range(80, 121)),
        None,
        [99, 100, 101, 102],
    )

    assert {
        (contract.strike, contract.right) for contract in hydration.contracts
    } == {
        (strike, right) for strike in (99, 100, 101, 102) for right in ("C", "P")
    }
    assert {
        request[1].strike
        for request in app.contract_detail_requests
        if request[1].strike > 0
    } == {99, 100, 101, 102}
    assert hydration.timed_out_strikes == frozenset()
    assert hydration.invalid_strikes == frozenset()
    assert hydration.skipped_strikes == frozenset(range(80, 121)) - {
        99,
        100,
        101,
        102,
    }


def test_ib_chain_provider_skips_broad_requests_that_timed_out_today():
    app = TimeoutBroadOptionChainIbApp(contract_strikes=[95, 100, 105])
    market_dates = [date(2026, 7, 1)]
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.05,
        current_date_provider=lambda: market_dates[-1],
    )

    def broad_request_count() -> int:
        return sum(
            1 for _req_id, contract in app.contract_detail_requests if contract.strike == 0
        )

    provider.fetch_chain_contract_hydration("hims", "2026-07-31", [95, 100])
    assert broad_request_count() == 1

    hydration = provider.fetch_chain_contract_hydration("hims", "2026-07-31", [105])
    assert broad_request_count() == 1
    assert {contract.strike for contract in hydration.contracts} == {105}

    market_dates.append(date(2026, 7, 2))
    provider.fetch_chain_contract_hydration("hims", "2026-07-31", [105])
    assert broad_request_count() == 2


def test_ib_chain_provider_skips_rights_already_resolved():
    app = FakeOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(app)

    hydration = provider.fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [95, 100],
        None,
        None,
        frozenset({(95, "P"), (100, "P")}),
    )

    assert [contract.right for _req_id, contract in app.contract_detail_requests] == [
        "C"
    ]
    assert {(contract.strike, contract.right) for contract in hydration.contracts} == {
        (95, "C"),
        (100, "C"),
    }


def test_ib_chain_provider_splits_one_broad_answer_by_right():
    app = FakeOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(app)

    hydration = provider.fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [95, 100],
        None,
        None,
        frozenset({(95, "P")}),
    )

    assert [contract.right for _req_id, contract in app.contract_detail_requests] == [
        ""
    ]
    assert {(contract.strike, contract.right) for contract in hydration.contracts} == {
        (95, "C"),
        (100, "C"),
        (100, "P"),
    }
    assert hydration.invalid_strikes == frozenset()


def test_ib_chain_provider_requests_calls_and_puts_in_one_broad_request():
    app = AllContractDetailsTimeoutOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.2,
        hydration_timeout_seconds=0.2,
    )

    started_at = perf_counter()
    hydration = provider.fetch_chain_contract_hydration(
        "hims",
        "2026-07-31",
        [95, 100],
    )
    elapsed = perf_counter() - started_at

    broad_rights = [
        request[1].right
        for request in app.contract_detail_requests
        if request[1].strike == 0
    ]
    assert broad_rights == [""]
    assert elapsed < 0.35
    assert hydration.timed_out_strikes == frozenset({95, 100})


def test_ib_chain_provider_skips_invalid_exact_option_contracts():
    app = InvalidExactOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(
        app,
        contract_timeout_seconds=0.01,
    )

    hydration = provider.fetch_chain_contract_hydration(
        "hims",
        "2026-07-24",
        [95, 100, 105],
    )

    assert {contract.strike for contract in hydration.contracts} == {95, 100}
    assert hydration.timed_out_strikes == frozenset()
    assert hydration.invalid_strikes == frozenset({105})
    assert app.request_errors_by_req_id == {}


def test_ib_chain_provider_rejects_invalid_underlying_from_broad_request():
    app = InvalidBroadOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(app)

    with pytest.raises(OptionsDataUnavailable, match="Invalid ticker: NOPE."):
        preferred_chain_contracts(provider.fetch_chain_contract_hydration(
            "nope",
            "2026-06-19",
            [100],
        ).contracts)


def test_ib_chain_provider_omits_unresolved_expiration_strikes():
    app = FakeOptionChainIbApp(contract_strikes=[95, 100])
    provider = IbOptionChainSnapshotProvider(app)

    contracts = preferred_chain_contracts(provider.fetch_chain_contract_hydration(
        "hims",
        "2026-06-19",
        [95, 100, 105],
    ).contracts)
    quotes = provider.fetch_chain_quotes(contracts)

    requested_contracts = [request[1] for request in app.market_data_requests]
    assert {contract.strike for contract in contracts} == {95, 100}
    assert {contract.strike for contract in requested_contracts} == {95, 100}
    assert set(quotes) == {
        (95, "C"),
        (95, "P"),
        (100, "C"),
        (100, "P"),
    }


def test_ib_chain_provider_waits_for_ticks_after_the_first_callback():
    app = SlowOptionChainIbApp()
    provider = IbOptionChainSnapshotProvider(
        app,
        timeout_seconds=0.05,
    )

    contracts = preferred_chain_contracts(provider.fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [100],
    ).contracts)
    quotes = provider.fetch_chain_quotes(contracts)

    assert quotes[(100, "C")].mid == 1.2
    assert quotes[(100, "P")].mid == 1.2


def test_ib_chain_stream_provider_cancels_subscriptions_on_close():
    app = FakeOptionChainIbApp()
    provider = IbOptionChainStreamProvider(app, wait_seconds=0.01)
    stop_event = threading.Event()
    contracts = preferred_chain_contracts(IbOptionChainSnapshotProvider(app).fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [100],
    ).contracts)
    stream = provider.stream_chain_quotes(
        contracts,
        stop_event,
    )

    quote_batch = next(stream)
    stop_event.set()
    stream.close()

    requested_contracts = [request[1] for request in app.market_data_requests]
    key, quote = quote_batch[0]
    assert key == (100, "C")
    assert quote.mid == 1.2
    assert {key for key, _quote in quote_batch} == {(100, "C"), (100, "P")}
    assert len(requested_contracts) == 2
    assert all(request[3] is False for request in app.market_data_requests)
    assert app.cancelled_market_data == [90_000, 90_001]
    assert app.option_market_req_to_key == {}
    assert app.option_market_data == {}


def test_ib_chain_stream_grows_into_released_lines_and_releases_on_close():
    app = FakeOptionChainIbApp()
    app.market_data_lines = MarketDataLineBudget(4)
    app.market_data_lines.try_acquire("screener", 2)
    provider = IbOptionChainStreamProvider(app, wait_seconds=0.01)
    contracts = preferred_chain_contracts(IbOptionChainSnapshotProvider(app).fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [95, 100],
    ).contracts)
    stream = provider.stream_chain_quotes(contracts, threading.Event())

    waiting = next(stream)
    assert isinstance(waiting, OptionChainStreamNotice)
    assert waiting.warning == (
        "Waiting for free IB market-data lines: streaming 2 of 4 contract(s)."
    )
    assert len(app.market_data_requests) == 2
    assert app.market_data_lines.try_acquire("screener", 1) == 0

    first_batch = next(stream)
    assert {key for key, _quote in first_batch} == {(95, "C"), (95, "P")}

    app.market_data_lines.release("screener", 2)
    assert next(stream) == OptionChainStreamNotice(warning=None)
    assert len(app.market_data_requests) == 4

    stream.close()

    assert app.market_data_lines.used() == 0
    assert app.market_data_lines.pending_by_owner == {}
    assert len(app.cancelled_market_data) == 4


def test_ib_chain_stream_warns_when_ib_rejects_lines():
    app = FakeOptionChainIbApp()
    app.limit_errors_by_req_id = {90_001: 101}
    provider = IbOptionChainStreamProvider(app, wait_seconds=0.01)
    contracts = preferred_chain_contracts(IbOptionChainSnapshotProvider(app).fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [100],
    ).contracts)
    stream = provider.stream_chain_quotes(contracts, threading.Event())

    notice = next(stream)
    stream.close()

    assert notice.warning == (
        "IB rejected 1 contract(s) at the market-data line limit; their quotes "
        "stay blank."
    )
    assert app.limit_errors_by_req_id == {}


def test_ib_chain_stream_provider_isolates_overlapping_stream_state():
    app = FakeOptionChainIbApp()
    provider = IbOptionChainStreamProvider(app, wait_seconds=0.01)
    first_stop_event = threading.Event()
    second_stop_event = threading.Event()
    first_contracts = preferred_chain_contracts(IbOptionChainSnapshotProvider(app).fetch_chain_contract_hydration(
        "aapl",
        "2026-06-19",
        [100],
    ).contracts)
    second_contracts = preferred_chain_contracts(IbOptionChainSnapshotProvider(app).fetch_chain_contract_hydration(
        "msft",
        "2026-06-19",
        [100],
    ).contracts)
    first_stream = provider.stream_chain_quotes(
        first_contracts,
        first_stop_event,
    )
    second_stream = provider.stream_chain_quotes(
        second_contracts,
        second_stop_event,
    )

    first_batch = next(first_stream)
    second_batch = next(second_stream)
    first_stream.close()

    first_key, first_quote = first_batch[0]
    second_key, second_quote = second_batch[0]
    assert first_key == (100, "C")
    assert first_quote.bid == 1
    assert second_key == (100, "C")
    assert second_quote.bid == 1
    assert app.cancelled_market_data == [90_000, 90_001]
    assert app.option_market_req_to_key == {
        90_002: (100, "C"),
        90_003: (100, "P"),
    }
    assert set(app.option_market_data) == {90_002, 90_003}

    second_stream.close()

    assert app.cancelled_market_data == [90_000, 90_001, 90_002, 90_003]
    assert app.option_market_req_to_key == {}
    assert app.option_market_data == {}


def test_concurrent_chain_streams_receive_updates_without_waiting_out_the_timeout():
    app = FakeOptionChainIbApp(contract_strikes=[100])
    provider = IbOptionChainStreamProvider(app, wait_seconds=5)
    snapshot_provider = IbOptionChainSnapshotProvider(app)
    streams = [
        provider.stream_chain_quotes(
            preferred_chain_contracts(snapshot_provider.fetch_chain_contract_hydration(ticker, "2026-06-19", [100]).contracts),
            threading.Event(),
        )
        for ticker in ("aapl", "msft")
    ]
    for stream in streams:
        next(stream)
    first_req_id, second_req_id = (
        app.market_data_requests[0][0],
        app.market_data_requests[-1][0],
    )

    deliver_ticks_later(app, 0.03, {first_req_id: {"bid": 2}})
    deliver_ticks_later(app, 0.05, {second_req_id: {"bid": 3}})
    started_at = perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        updates = list(executor.map(next, streams))

    assert perf_counter() - started_at < 1
    assert [[quote.bid for _key, quote in update] for update in updates] == [
        [2],
        [3],
    ]
    for stream in streams:
        stream.close()


def rotation_contracts(strikes):
    return [
        ScannerOptionContract(
            con_id=int(strike * 10) + (1 if right == "C" else 2),
            ticker="AAPL",
            expiration="2026-06-19",
            strike=strike,
            right=right,
            exchange="SMART",
            currency="USD",
            multiplier="100",
            trading_class="AAPL",
            local_symbol=f"AAPL{strike}{right}",
        )
        for strike in strikes
        for right in ("C", "P")
    ]


ROTATION_STRIKES = [80, 85, 90, 95, 100, 105, 110, 115, 120]


def make_rotation():
    return OptionChainRotation(
        "AAPL",
        "2026-06-19",
        ROTATION_STRIKES,
        rotation_contracts(ROTATION_STRIKES),
        [95, 100, 105],
        101,
    )


def batch_strikes(batch):
    return sorted({contract.strike for contract in batch})


def rotation_pass(rotation):
    strikes = batch_strikes(rotation.next_batch(4))
    while rotation.pending_strikes:
        strikes += batch_strikes(rotation.next_batch(4))
    return sorted(strikes)


def test_chain_rotation_first_pass_goes_outward_in_whole_strikes():
    rotation = make_rotation()

    batches = [rotation.next_batch(4) for _ in range(3)]

    assert [[contract.strike for contract in batch] for batch in batches] == [
        [110, 110, 90, 90],
        [115, 115, 85, 85],
        [120, 120, 80, 80],
    ]
    assert rotation.pending_strikes == []


def test_chain_rotation_later_passes_follow_and_widen_with_delta_bounds():
    rotation = make_rotation()
    assert rotation_pass(rotation) == [80, 85, 90, 110, 115, 120]

    rotation.observe({}, (90, 110))
    assert rotation_pass(rotation) == [85, 90, 110, 115]

    rotation.observe({}, (85, 115))
    assert rotation_pass(rotation) == [80, 85, 90, 110, 115, 120]


def test_chain_rotation_recenters_only_after_a_large_move():
    rotation = make_rotation()

    rotation.observe({(110, "C"): OptionQuote(delta=0.5)}, (None, None))
    assert rotation.live_strikes == [95, 100, 105]

    rotation.observe({(115, "C"): OptionQuote(delta=0.52)}, (None, None))
    assert rotation.live_strikes == [110, 115, 120]
    assert {contract.strike for contract in rotation.live_contracts()} == {
        110,
        115,
        120,
    }
    assert rotation_pass(rotation) == [80, 85, 90, 95, 100, 105]


class LineCountingOptionChainIbApp(FakeOptionChainIbApp):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.active_req_ids: set[int] = set()
        self.max_active_req_ids = 0
        self.req_id_strikes: dict[int, float] = {}

    def reqMktData(self, req_id, contract, *args) -> None:
        super().reqMktData(req_id, contract, *args)
        with self.lock:
            self.req_id_strikes[req_id] = contract.strike
            self.active_req_ids.add(req_id)
            self.max_active_req_ids = max(
                self.max_active_req_ids,
                len(self.active_req_ids),
            )

    def cancelMktData(self, req_id) -> None:
        super().cancelMktData(req_id)
        with self.lock:
            self.active_req_ids.discard(req_id)

    def active_strikes(self) -> set[float]:
        with self.lock:
            return {self.req_id_strikes[req_id] for req_id in self.active_req_ids}


def start_rotating_stream(app, rotation, stop_event):
    provider = IbOptionChainStreamProvider(
        app,
        wait_seconds=0.05,
        rotation_lines=4,
        rotation_wait_seconds=0.2,
        rotation_idle_seconds=0.02,
    )
    return provider.stream_chain_quotes(
        rotation.live_contracts(),
        stop_event,
        rotation,
    )


def rotating_app():
    app = LineCountingOptionChainIbApp(contract_strikes=ROTATION_STRIKES)
    # Live window 3 strikes (6 lines) plus 4 rotation lines.
    app.market_data_lines = MarketDataLineBudget(10)
    return app


def test_chain_stream_quotes_every_displayed_strike_within_its_allocation():
    app = rotating_app()
    stop_event = threading.Event()
    stream = start_rotating_stream(app, make_rotation(), stop_event)
    expected = {(strike, right) for strike in ROTATION_STRIKES for right in "CP"}

    quoted: set[tuple[float, str]] = set()
    deadline = perf_counter() + 3
    while quoted != expected and perf_counter() < deadline:
        quoted.update(key for key, _quote in next(stream))
    stream.close()

    assert quoted == expected
    assert app.max_active_req_ids <= 10
    assert app.active_req_ids == set()
    assert app.market_data_lines.used() == 0


def test_chain_stream_stops_rotation_promptly_and_releases_every_line():
    app = rotating_app()
    stop_event = threading.Event()
    stream = start_rotating_stream(app, make_rotation(), stop_event)
    next(stream)

    stop_event.set()
    started_at = perf_counter()
    list(stream)

    assert perf_counter() - started_at < 1
    assert not any(
        thread.name == "option-chain-rotation" for thread in threading.enumerate()
    )
    assert app.active_req_ids == set()
    assert app.market_data_lines.used() == 0


def test_chain_stream_moves_live_subscriptions_when_the_window_recenters():
    app = rotating_app()
    rotation = make_rotation()
    stream = start_rotating_stream(app, rotation, threading.Event())
    next(stream)
    old_live_req_ids = {
        req_id
        for req_id, strike in app.req_id_strikes.items()
        if strike in {95, 100, 105}
    }
    assert len(old_live_req_ids) == 6

    rotation.observe({(115, "C"): OptionQuote(delta=0.5)}, (None, None))
    deadline = perf_counter() + 2
    while perf_counter() < deadline and not (
        {110, 115, 120} <= app.active_strikes()
        and old_live_req_ids <= set(app.cancelled_market_data)
    ):
        next(stream)
    stream.close()

    assert old_live_req_ids <= set(app.cancelled_market_data)
    assert app.max_active_req_ids <= 10
    assert app.market_data_lines.used() == 0