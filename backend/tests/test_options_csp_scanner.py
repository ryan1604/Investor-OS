from datetime import date, datetime
import threading
from zoneinfo import ZoneInfo

from app.options.client import (
    FullOptionChainSnapshot,
    OptionsClient,
    ScannerContractSelection,
    ScannerOptionContract,
    ScannerOptionQuote,
)
from app.ib.options import IbOptionScannerProvider
from app.options.domain import OptionMetadata
from app.options.store import CompletedDailyBar, OptionsDailyBarStore
from app.options_screeners.service import OptionsScreenerServiceUnavailable
from app.options_screeners.single_leg import SingleLegOptionsScreenerScanService
from app.schemas import (
    OptionContractIdentity,
    OptionsScreenerFilters,
    OptionsScreenerQuoteRefreshRequest,
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
    def fetch_expirations(self, ticker):
        return self.fetch_option_metadata(ticker).expirations

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
        expirations,
        strikes,
        right,
        cancel_event,
    ):
        self.contract_request = (ticker, expirations, strikes, right)
        return ScannerContractSelection(
            contracts=[
                contract(expiration, strike, con_id=index)
                for index, (expiration, strike) in enumerate(
                    (
                        (expiration, strike)
                        for expiration in expirations
                        for strike in strikes
                    ),
                    start=1,
                )
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
            contract=contract(
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
        ["2026-06-22", "2026-06-26", "2026-07-30"],
        [80, 85, 90, 95],
        "P",
    )
    assert len(snapshot.contracts) == 12
    assert snapshot.underlying_price == 100


class FullChainClient:
    def __init__(self, quotes):
        self.quotes = quotes
        self.requests = []
        self.cancelled = False

    def get_full_option_chain(self, ticker, **kwargs):
        self.requests.append((ticker, kwargs))
        return FullOptionChainSnapshot(
            ticker=ticker,
            underlying_price=100,
            underlying_price_captured_at=datetime(
                2026,
                6,
                15,
                10,
                tzinfo=ZoneInfo("America/New_York"),
            ),
            contracts=self.quotes,
        )

    def cancel_scanner(self):
        self.cancelled = True

    def refresh_option_quote(self, **kwargs):
        return self.quotes[0]


def test_csp_scanner_deduplicates_and_excludes_invalid_contracts():
    quotes = [
        quote("2026-06-22", 90, 1, exchange="CBOE"),
        quote("2026-06-22", 90, 2, exchange="SMART"),
        quote("2026-06-26", 95, 3, bid=0),
        quote("2026-06-26", 94, 4, bid=2, ask=1),
        quote("2026-06-26", 93, 5, delta=None),
        quote("2026-06-15", 92, 6),
        quote("2026-06-26", 100, 7),
        quote("2026-06-26", 91, 8, multiplier="10"),
        quote("2026-06-26", 89, 9, trading_class="AAPL1"),
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
        ScannerOptionQuote(
            contract=contract(
                "2026-07-15",
                99 - (index / 1000),
                con_id=index,
            ),
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


def test_ib_scanner_quotes_contracts_in_bounded_batches():
    app = FakeScannerApp()
    provider = IbOptionScannerProvider(
        app,
        quote_wait_seconds=0,
        quote_batch_size=2,
    )
    contracts = [
        contract("2026-07-17", 90 + index, con_id=index)
        for index in range(1, 6)
    ]

    quotes = provider.fetch_quotes(contracts, threading.Event())

    assert len(quotes) == 5
    assert app.max_active_market_requests == 2
    assert len(app.cancelled_market_requests) == 5
    assert provider.active_req_ids == set()


def test_csp_quote_refresh_returns_resolved_identity_and_current_midpoint():
    service = SingleLegOptionsScreenerScanService(
        FullChainClient([quote("2026-07-17", 100, 456, bid=1, ask=1.4)]),
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
        FullChainClient([quote("2026-07-17", 100, 456, bid=0, ask=1.4)]),
    )

    try:
        service.refresh_quote(refresh_request())
    except OptionsScreenerServiceUnavailable as error:
        assert "valid current quote" in str(error)
    else:
        raise AssertionError("Expected an invalid refreshed quote to be rejected.")


def contract(
    expiration,
    strike,
    *,
    con_id,
    exchange="SMART",
    multiplier="100",
    trading_class="AAPL",
):
    return ScannerOptionContract(
        con_id=con_id,
        ticker="AAPL",
        expiration=expiration,
        strike=strike,
        right="P",
        exchange=exchange,
        currency="USD",
        multiplier=multiplier,
        trading_class=trading_class,
        local_symbol=f"AAPL {expiration} {strike} P",
    )


def quote(
    expiration,
    strike,
    con_id,
    *,
    exchange="SMART",
    multiplier="100",
    trading_class="AAPL",
    bid=1,
    ask=1.1,
    delta=-0.2,
):
    return ScannerOptionQuote(
        contract=contract(
            expiration,
            strike,
            con_id=con_id,
            exchange=exchange,
            multiplier=multiplier,
            trading_class=trading_class,
        ),
        bid=bid,
        ask=ask,
        delta=delta,
    )


def refresh_request():
    return OptionsScreenerQuoteRefreshRequest(
        ticker="AAPL",
        expiration="2026-07-17",
        strike=100,
        right="PUT",
        contract=OptionContractIdentity(
            con_id=123,
            local_symbol="AAPL 2026-07-17 100 P",
        ),
    )


class FakeScannerApp:
    def __init__(self):
        self.lock = threading.Lock()
        self.option_market_data_ready = threading.Event()
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
        self.option_market_data[req_id] = {
            "bid": 1,
            "ask": 1.2,
            "delta": -0.2,
        }

    def cancelMktData(self, req_id):
        self.cancelled_market_requests.append(req_id)
        self.active_market_requests.discard(req_id)
