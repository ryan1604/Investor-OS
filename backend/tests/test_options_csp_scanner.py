from datetime import date
import threading
from time import perf_counter

from app.ib.market_data_lines import MarketDataLineBudget
from app.options.client import (
    OptionChainContractHydration,
    OptionContractCache,
    OptionsClient,
    OptionsDataUnavailable,
    ScannerContractSelection,
    ScannerOptionQuote,
)
from app.ib.options import IbOptionScannerProvider
from app.options.domain import OptionMetadata
from app.options.store import CompletedDailyBar, OptionsDailyBarStore
from app.options_screeners.service import OptionsScreenerServiceUnavailable
from app.options_screeners.single_leg import SingleLegOptionsScreenerScanService
from app.schemas import (
    OptionsScreenerFilters,
)
from options_screener_helpers import (
    FullChainClient,
    contract,
    put_contract,
    put_quote,
    refresh_request,
)


class HistoricalProvider:
    def __init__(self) -> None:
        self.requests = []

    def fetch_daily_bars(self, ticker, start_date, end_date):
        self.requests.append((ticker, start_date, end_date))
        return [
            CompletedDailyBar(
                ticker=ticker,
                trading_date=end_date.isoformat(),
                open=100,
                high=101,
                low=99,
                close=100,
            )
        ]


class MetadataProvider:
    def fetch_option_metadata(self, ticker):
        return OptionMetadata(
            expirations=[
                "2026-06-15",
                "2026-06-22",
                "2026-06-26",
                "2026-07-30",
            ],
            strikes=[80, 85, 90, 95, 100, 105],
        )


class ScannerProvider:
    def __init__(self) -> None:
        self.contract_request = None
        self.quote_request = None

    def fetch_option_contracts(
        self,
        ticker,
        lookups,
        right,
        cancel_event,
    ):
        self.contract_request = (ticker, lookups, right)
        return ScannerContractSelection(
            contracts=[
                put_contract(expiration, strike, con_id=index)
                for index, (expiration, strike) in enumerate(lookups, start=1)
            ]
        )

    def fetch_quotes(self, contracts, cancel_event):
        self.quote_request = contracts
        return [
            ScannerOptionQuote(
                contract=current,
                bid=1,
                ask=1.1,
                delta=-0.2,
            )
            for current in contracts
        ]

    def refresh_quote(self, **kwargs):
        return ScannerOptionQuote(
            contract=put_contract(
                kwargs["expiration"],
                kwargs["strike"],
                con_id=kwargs["con_id"] or 99,
            ),
            bid=1,
            ask=1.2,
            delta=-0.2,
        )

    def cancel(self):
        return


class EmptyProvider:
    def fetch_chain_quotes(self, ticker, expiration, strikes):
        return {}

    def stream_chain_quotes(self, ticker, expiration, strikes, stop_event):
        return iter(())

    def stream_daily_bar_updates(self, ticker, stop_event):
        return iter(())


def test_full_put_chain_scans_every_otm_strike_and_inclusive_expiration(tmp_path):
    historical = HistoricalProvider()
    scanner = ScannerProvider()
    empty = EmptyProvider()
    client = OptionsClient(
        OptionsDailyBarStore(tmp_path / "options.sqlite3"),
        historical,
        MetadataProvider(),
        empty,
        empty,
        empty,
        scanner_provider=scanner,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    snapshot = client.get_full_option_chain(
        "AAPL",
        right="P",
        minimum_dte=7,
        maximum_dte=45,
        cancel_event=threading.Event(),
    )

    assert historical.requests == [
        ("AAPL", date(2026, 6, 8), date(2026, 6, 15))
    ]
    assert scanner.contract_request == (
        "AAPL",
        [
            (expiration, strike)
            for expiration in ["2026-06-22", "2026-06-26", "2026-07-30"]
            for strike in [80, 85, 90, 95]
        ],
        "P",
    )
    assert len(snapshot.contracts) == 12
    assert snapshot.underlying_price == 100


def test_csp_scanner_deduplicates_and_excludes_invalid_contracts():
    quotes = [
        put_quote("2026-06-22", 90, 1, exchange="CBOE"),
        put_quote("2026-06-22", 90, 2, exchange="SMART"),
        put_quote("2026-06-26", 95, 3, bid=0),
        put_quote("2026-06-26", 94, 4, bid=2, ask=1),
        put_quote("2026-06-26", 93, 5, delta=None),
        put_quote("2026-06-15", 92, 6),
        put_quote("2026-06-26", 100, 7),
        put_quote("2026-06-26", 91, 8, multiplier="10"),
        put_quote("2026-06-26", 89, 9, trading_class="AAPL1"),
    ]
    client = FullChainClient(quotes)
    service = SingleLegOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "csp",
        "AAPL",
        OptionsScreenerFilters(minimum_annualized_return=0),
        threading.Event(),
    )

    assert [item.contract.con_id for item in result.candidates] == [2]
    assert result.excluded_contracts == 8
    assert result.warnings[0].category == "excluded_contracts"
    assert result.warnings[0].count == 8


def test_csp_scanner_uses_raw_inclusive_filter_values_across_large_chain():
    quotes = [
        put_quote(
            "2026-07-15",
            99 - (index / 1000),
            index,
            bid=1,
            ask=1.2,
            delta=-0.15 if index == 1 else -0.30,
        )
        for index in range(1, 601)
    ]
    service = SingleLegOptionsScreenerScanService(
        FullChainClient(quotes),
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "csp",
        "AAPL",
        OptionsScreenerFilters(minimum_annualized_return=0),
        threading.Event(),
    )

    assert len(result.candidates) == 600
    assert result.excluded_contracts == 0
    assert result.candidates[0].annualized_return >= result.candidates[-1].annualized_return


def test_csp_scanner_reports_no_matches_and_propagates_cancellation():
    client = FullChainClient([])
    service = SingleLegOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "csp",
        "AAPL",
        OptionsScreenerFilters(),
        threading.Event(),
    )
    service.cancel()

    assert [warning.category for warning in result.warnings] == ["no_matches"]
    assert client.cancelled


def test_ib_scanner_quotes_contracts_in_a_bounded_window():
    app = FakeScannerApp()
    provider = IbOptionScannerProvider(
        app,
        quote_wait_seconds=0,
        quote_window_size=2,
    )
    contracts = [
        put_contract("2026-07-17", 90 + index, con_id=index)
        for index in range(1, 6)
    ]

    quotes = provider.fetch_quotes(contracts, threading.Event())

    assert len(quotes) == 5
    assert app.max_active_market_requests == 2
    assert len(app.cancelled_market_requests) == 5
    assert provider.active_req_ids == set()


def test_ib_scanner_reuses_a_line_while_a_slow_greek_is_pending():
    app = ScheduledTickScannerApp(
        {1: [(0.3, {"bid": 1, "ask": 1.2, "delta": -0.2})]},
    )
    provider = IbOptionScannerProvider(app, quote_wait_seconds=4, quote_window_size=2)
    contracts = [
        put_contract("2026-07-17", 90 + index, con_id=index) for index in range(1, 5)
    ]
    started_at = perf_counter()

    quotes = provider.fetch_quotes(contracts, threading.Event())

    assert perf_counter() - started_at < 1
    assert [quote.contract.con_id for quote in quotes] == [1, 2, 3, 4]
    assert all(quote.delta == -0.2 for quote in quotes)
    # Contracts 3 and 4 used the line contract 2 freed while 1 still waited.
    assert app.requested_before_cancel(4, 1)
    assert app.max_active_market_requests == 2


def test_ib_scanner_quote_waits_for_its_delta_past_the_settle_interval():
    app = ScheduledTickScannerApp(
        {
            1: [
                (0, {"bid": 1, "ask": 1.2}),
                (0.2, {"delta": -0.2}),
            ]
        },
    )
    provider = IbOptionScannerProvider(
        app,
        quote_wait_seconds=4,
        quote_settle_seconds=0.05,
    )

    quotes = provider.fetch_quotes(
        [put_contract("2026-07-17", 95, con_id=1)],
        threading.Event(),
    )

    assert quotes[0].delta == -0.2


def test_ib_scanner_quote_without_a_bid_settles_before_the_maximum_wait():
    app = ScheduledTickScannerApp({1: [(0, {"ask": 0.05, "delta": -0.01})]})
    provider = IbOptionScannerProvider(
        app,
        quote_wait_seconds=4,
        quote_settle_seconds=0.05,
    )
    started_at = perf_counter()

    quotes = provider.fetch_quotes(
        [put_contract("2026-07-17", 95, con_id=1)],
        threading.Event(),
    )

    assert perf_counter() - started_at < 1
    assert (quotes[0].bid, quotes[0].ask, quotes[0].delta) == (None, 0.05, -0.01)


def test_ib_scanner_quote_that_never_arrives_ends_at_the_maximum_wait():
    app = ScheduledTickScannerApp({1: []})
    provider = IbOptionScannerProvider(app, quote_wait_seconds=0.2)
    started_at = perf_counter()

    quotes = provider.fetch_quotes(
        [
            put_contract("2026-07-17", 95, con_id=1),
            put_contract("2026-07-17", 90, con_id=2),
        ],
        threading.Event(),
    )

    assert 0.18 <= perf_counter() - started_at < 1
    assert [(quote.bid, quote.delta) for quote in quotes] == [
        (None, None),
        (1, -0.2),
    ]
    assert app.active_market_requests == set()


def test_ib_scanner_window_gives_freed_lines_to_a_waiting_chain():
    app = ScheduledTickScannerApp(
        {1: [(0.3, {"bid": 1, "ask": 1.2, "delta": -0.2})]},
        tick_delay=0.02,
    )
    app.market_data_lines = MarketDataLineBudget(2)
    provider = IbOptionScannerProvider(app, quote_wait_seconds=4)
    contracts = [
        put_contract("2026-07-17", 90 + index, con_id=index) for index in range(1, 6)
    ]
    chain_granted = []

    def open_chain():
        chain_granted.append(app.market_data_lines.acquire("chain", 1, timeout=1))

    threading.Timer(0.01, open_chain).start()
    quotes = provider.fetch_quotes(contracts, threading.Event())

    assert chain_granted == [1]
    assert len(quotes) == 5
    assert app.market_data_lines.usage_by_group() == {"chain": 1}


def test_ib_scanner_cancellation_returns_partial_quotes_and_releases_lines():
    app = ScheduledTickScannerApp({1: [], 2: []})
    app.market_data_lines = MarketDataLineBudget(5)
    provider = IbOptionScannerProvider(app, quote_wait_seconds=4)
    cancel_event = threading.Event()
    threading.Timer(0.05, cancel_event.set).start()
    started_at = perf_counter()

    quotes = provider.fetch_quotes(
        [
            put_contract("2026-07-17", 95, con_id=1),
            put_contract("2026-07-17", 90, con_id=2),
        ],
        cancel_event,
    )

    assert perf_counter() - started_at < 1
    assert [quote.bid for quote in quotes] == [None, None]
    assert app.active_market_requests == set()
    assert app.market_data_lines.usage_by_group() == {}
    assert provider.active_req_ids == set()


class CachingScannerProvider(ScannerProvider):
    def __init__(self, invalid=(), timed_out=()) -> None:
        super().__init__()
        self.lookup_requests = []
        self.invalid = set(invalid)
        self.timed_out = set(timed_out)

    def fetch_option_contracts(self, ticker, lookups, right, cancel_event):
        self.lookup_requests.append(list(lookups))
        requested = set(lookups)
        valid = [
            lookup
            for lookup in lookups
            if lookup not in self.invalid and lookup not in self.timed_out
        ]
        return ScannerContractSelection(
            contracts=[
                put_contract(expiration, strike, con_id=int(strike))
                for expiration, strike in valid
            ],
            excluded_contracts=len(lookups) - len(valid),
            invalid_lookups=frozenset(self.invalid & requested),
            timed_out_lookups=frozenset(self.timed_out & requested),
        )


class RecordingChainContractProvider(EmptyProvider):
    def __init__(self) -> None:
        self.requests = []

    def fetch_chain_contract_hydration(
        self,
        ticker,
        expiration,
        strikes,
        stop_event=None,
        fallback_strikes=None,
        resolved_keys=frozenset(),
        priority=None,
    ):
        self.requests.append((list(strikes), resolved_keys))
        return OptionChainContractHydration(
            contracts=[
                contract(
                    expiration,
                    strike,
                    con_id=int(strike * 10) + (1 if right == "C" else 2),
                    right=right,
                )
                for strike in strikes
                for right in ("C", "P")
                if (strike, right) not in resolved_keys
            ]
        )


def make_cached_scan_client(tmp_path, scanner, chain_provider=None):
    empty = EmptyProvider()
    return OptionsClient(
        OptionsDailyBarStore(tmp_path / "options.sqlite3"),
        HistoricalProvider(),
        MetadataProvider(),
        chain_provider or empty,
        empty,
        empty,
        scanner_provider=scanner,
        current_date_provider=lambda: date(2026, 6, 15),
    )


def scan_puts(client):
    return client.get_full_option_chain(
        "AAPL",
        right="P",
        minimum_dte=7,
        maximum_dte=45,
        cancel_event=threading.Event(),
    )


def test_repeated_scan_requests_only_timed_out_contracts(tmp_path):
    scanner = CachingScannerProvider(
        invalid={("2026-06-22", 80)},
        timed_out={("2026-06-26", 85)},
    )
    client = make_cached_scan_client(tmp_path, scanner)

    first = scan_puts(client)
    second = scan_puts(client)

    assert len(scanner.lookup_requests[0]) == 12
    assert scanner.lookup_requests[1] == [("2026-06-26", 85)]
    assert first.excluded_contracts == second.excluded_contracts == 2
    assert [quote.contract for quote in second.contracts] == [
        quote.contract for quote in first.contracts
    ]


def test_chain_load_reuses_contracts_resolved_by_a_scan(tmp_path):
    chain_provider = RecordingChainContractProvider()
    client = make_cached_scan_client(
        tmp_path,
        CachingScannerProvider(invalid={("2026-06-22", 80)}),
        chain_provider,
    )

    scan_puts(client)
    context = client.chain_context("AAPL", "2026-06-22")

    assert chain_provider.requests == [
        (
            [80, 85, 90, 95, 100, 105],
            frozenset({(80, "P"), (85, "P"), (90, "P"), (95, "P")}),
        )
    ]
    assert {(item.strike, item.right) for item in context.contracts} == {
        (strike, right)
        for strike in (80, 85, 90, 95, 100, 105)
        for right in ("C", "P")
    } - {(80, "P")}


def test_scan_reuses_contracts_resolved_by_a_chain_load(tmp_path):
    scanner = CachingScannerProvider()
    client = make_cached_scan_client(
        tmp_path,
        scanner,
        RecordingChainContractProvider(),
    )

    client.chain_context("AAPL", "2026-06-22")
    snapshot = scan_puts(client)

    assert scanner.lookup_requests == [
        [
            (expiration, strike)
            for expiration in ("2026-06-26", "2026-07-30")
            for strike in (80, 85, 90, 95)
        ]
    ]
    assert len(snapshot.contracts) == 12


def test_contract_cache_expires_at_the_market_date_change():
    market_dates = [date(2026, 6, 15)]
    cache = OptionContractCache(lambda: market_dates[-1])
    cache.store(
        "AAPL",
        "P",
        {
            ("2026-06-22", 95): [put_contract("2026-06-22", 95, con_id=1)],
            ("2026-06-22", 90): [],
        },
    )
    cache.remember_chain_skipped_strikes("AAPL", "2026-06-22", [80])

    assert set(cache.get_many("AAPL", "P", [("2026-06-22", 95), ("2026-06-22", 90)])) == {
        ("2026-06-22", 95),
        ("2026-06-22", 90),
    }

    market_dates.append(date(2026, 6, 16))

    assert cache.get_many("AAPL", "P", [("2026-06-22", 95)]) == {}
    assert cache.chain_skipped_strikes("AAPL", "2026-06-22") == frozenset()


def test_ib_scanner_batches_shrink_to_free_market_data_lines():
    app = FakeScannerApp()
    app.market_data_lines = MarketDataLineBudget(3)
    app.market_data_lines.try_acquire("chain", 1)
    provider = IbOptionScannerProvider(app, quote_wait_seconds=0)
    contracts = [
        put_contract("2026-07-17", 90 + index, con_id=index)
        for index in range(1, 6)
    ]

    quotes = provider.fetch_quotes(contracts, threading.Event())

    assert [quote.contract.con_id for quote in quotes] == [1, 2, 3, 4, 5]
    assert app.max_active_market_requests == 2
    assert app.market_data_lines.usage_by_group() == {"chain": 1}


def test_ib_scanner_stops_waiting_for_lines_when_cancelled():
    app = FakeScannerApp()
    app.market_data_lines = MarketDataLineBudget(1)
    app.market_data_lines.try_acquire("chain", 1)
    provider = IbOptionScannerProvider(app, quote_wait_seconds=0)
    cancel_event = threading.Event()
    threading.Timer(0.05, cancel_event.set).start()

    quotes = provider.fetch_quotes(
        [put_contract("2026-07-17", 95, con_id=1)],
        cancel_event,
    )

    assert quotes == []
    assert app.active_market_requests == set()
    assert app.market_data_lines.pending_by_owner == {}


def test_ib_scanner_flags_contracts_rejected_at_line_limit():
    app = FakeScannerApp()
    app.limit_errors_by_req_id = {}
    app.rejected_req_ids = {2}
    provider = IbOptionScannerProvider(app, quote_wait_seconds=0)

    quotes = provider.fetch_quotes(
        [
            put_contract("2026-07-17", 95, con_id=1),
            put_contract("2026-07-17", 90, con_id=2),
        ],
        threading.Event(),
    )

    assert [quote.line_limited for quote in quotes] == [False, True]
    assert quotes[1].bid is None
    assert app.limit_errors_by_req_id == {}


def test_csp_scanner_warns_about_line_limited_contracts():
    client = FullChainClient([put_quote("2026-07-17", 95, 1, bid=1, ask=1.2)])
    client.line_limited_contracts = 3
    service = SingleLegOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "csp",
        "AAPL",
        OptionsScreenerFilters(),
        threading.Event(),
    )

    warning = next(
        warning for warning in result.warnings if warning.category == "line_limit"
    )
    assert warning.count == 3


def test_ib_quote_refresh_fails_when_no_market_data_line_is_free():
    app = FakeScannerApp()
    app.market_data_lines = MarketDataLineBudget(1)
    app.market_data_lines.try_acquire("chain", 1)
    provider = IbOptionScannerProvider(app, quote_wait_seconds=0.01)
    provider._resolve_option_contracts = lambda *args: [
        put_contract("2026-07-17", 95, con_id=1)
    ]

    try:
        provider.refresh_quote(
            ticker="AAPL",
            expiration="2026-07-17",
            strike=95,
            right="P",
            con_id=1,
            local_symbol=None,
        )
    except OptionsDataUnavailable as error:
        assert "market-data line" in str(error)
    else:
        raise AssertionError("Expected the refresh to fail without a free line.")
    assert app.active_market_requests == set()


def test_csp_quote_refresh_returns_resolved_identity_and_current_midpoint():
    service = SingleLegOptionsScreenerScanService(
        FullChainClient([put_quote("2026-07-17", 100, 456, bid=1, ask=1.4)]),
    )

    refreshed = service.refresh_quote(refresh_request())

    assert refreshed.contract.con_id == 456
    assert refreshed.bid == 1
    assert refreshed.ask == 1.4
    assert refreshed.midpoint == 1.2
    assert refreshed.right == "PUT"
    assert refreshed.refreshed_at.endswith("+00:00")


def test_csp_quote_refresh_rejects_missing_current_market():
    service = SingleLegOptionsScreenerScanService(
        FullChainClient([put_quote("2026-07-17", 100, 456, bid=0, ask=1.4)]),
    )

    try:
        service.refresh_quote(refresh_request())
    except OptionsScreenerServiceUnavailable as error:
        assert "valid current quote" in str(error)
    else:
        raise AssertionError("Expected an invalid refreshed quote to be rejected.")


class FakeScannerApp:
    def __init__(self):
        self.lock = threading.Lock()
        self.option_market_ready_by_req_id = {}
        self.next_option_market_req_id = 1
        self.option_market_req_to_key = {}
        self.option_market_data = {}
        self.active_market_requests = set()
        self.cancelled_market_requests = []
        self.max_active_market_requests = 0

    def isConnected(self):
        return True

    def reqMarketDataType(self, market_data_type):
        return

    def reqMktData(
        self,
        req_id,
        contract,
        generic_ticks,
        snapshot,
        regulatory_snapshot,
        options,
    ):
        self.active_market_requests.add(req_id)
        self.max_active_market_requests = max(
            self.max_active_market_requests,
            len(self.active_market_requests),
        )
        if req_id in getattr(self, "rejected_req_ids", set()):
            self.limit_errors_by_req_id[req_id] = 101
            return
        self.option_market_data[req_id] = {
            "bid": 1,
            "ask": 1.2,
            "delta": -0.2,
        }

    def cancelMktData(self, req_id):
        self.cancelled_market_requests.append(req_id)
        self.active_market_requests.discard(req_id)


class ScheduledTickScannerApp(FakeScannerApp):
    """Deliver each contract's ticks on its own schedule after subscribing.

    Contracts without a schedule get a full quote after `tick_delay`.
    """

    def __init__(self, schedules, *, tick_delay=0):
        super().__init__()
        self.schedules = schedules
        self.tick_delay = tick_delay
        self.events = []

    def reqMktData(
        self,
        req_id,
        contract,
        generic_ticks,
        snapshot,
        regulatory_snapshot,
        options,
    ):
        self.active_market_requests.add(req_id)
        self.max_active_market_requests = max(
            self.max_active_market_requests,
            len(self.active_market_requests),
        )
        self.events.append(("request", contract.conId, req_id))
        schedule = self.schedules.get(
            contract.conId,
            [(self.tick_delay, {"bid": 1, "ask": 1.2, "delta": -0.2})],
        )
        for delay, ticks in schedule:
            threading.Timer(delay, self.deliver, (req_id, ticks)).start()

    def deliver(self, req_id, ticks):
        with self.lock:
            if req_id not in self.option_market_data:
                return
            self.option_market_data[req_id].update(ticks)
            ready = self.option_market_ready_by_req_id.get(req_id)
        if ready is not None:
            ready.set()

    def cancelMktData(self, req_id):
        con_id = next(
            con_id
            for event, con_id, event_req_id in self.events
            if event == "request" and event_req_id == req_id
        )
        self.events.append(("cancel", con_id, req_id))
        super().cancelMktData(req_id)

    def requested_before_cancel(self, requested_con_id, cancelled_con_id):
        order = [(event, con_id) for event, con_id, _req_id in self.events]
        return order.index(("request", requested_con_id)) < order.index(
            ("cancel", cancelled_con_id)
        )
