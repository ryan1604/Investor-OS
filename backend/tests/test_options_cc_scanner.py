from datetime import date
import threading

import pytest

from app.options.client import (
    OptionsClient,
    ScannerContractSelection,
    ScannerOptionQuote,
)
from app.options.domain import OptionMetadata
from app.options.store import CompletedDailyBar, OptionsDailyBarStore
from app.options_screeners.single_leg import SingleLegOptionsScreenerScanService
from app.schemas import (
    OptionsScreenerFilters,
)
from options_screener_helpers import (
    FullChainClient,
    call_contract,
    call_quote,
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
            strikes=[95, 100, 105, 110, 115],
        )


class ScannerProvider:
    def __init__(self) -> None:
        self.contract_request = None

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
                call_contract(expiration, strike, con_id=index)
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
        return [
            ScannerOptionQuote(
                contract=current,
                bid=1,
                ask=1.2,
                delta=0.2,
            )
            for current in contracts
        ]

    def cancel(self):
        return


class EmptyProvider:
    def fetch_chain_quotes(self, ticker, expiration, strikes):
        return {}

    def stream_chain_quotes(self, ticker, expiration, strikes, stop_event):
        return iter(())

    def stream_daily_bar_updates(self, ticker, stop_event):
        return iter(())


def test_full_call_chain_scans_every_otm_strike_and_inclusive_expiration(
    tmp_path,
):
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
        right="C",
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
        [105, 110, 115],
        "C",
    )
    assert len(snapshot.contracts) == 9
    assert snapshot.underlying_price == 100


def test_cc_scanner_uses_stock_price_return_and_gain_without_positions():
    client = FullChainClient(
        [
            call_quote("2026-07-15", 110, 1, bid=1.9, ask=2.1, delta=0.2),
            call_quote("2026-07-15", 120, 2, bid=0.9, ask=1.1, delta=0.15),
        ]
    )
    service = SingleLegOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cc",
        "AAPL",
        OptionsScreenerFilters(minimum_annualized_return=0),
        threading.Event(),
    )

    assert client.requests[0][1]["right"] == "C"
    assert [candidate.contract.con_id for candidate in result.candidates] == [1, 2]
    assert result.candidates[0].annualized_return == pytest.approx(
        (2 / 100) * (365 / 30) * 100
    )
    assert result.candidates[0].gain_percentage == pytest.approx(10)


def test_cc_scanner_applies_shared_exclusions_deduplication_and_filters():
    quotes = [
        call_quote("2026-07-15", 110, 1, exchange="CBOE"),
        call_quote("2026-07-15", 110, 2, exchange="SMART"),
        call_quote("2026-07-15", 100, 3),
        put_quote("2026-07-15", 105, 4),
        call_quote("2026-07-15", 115, 5, bid=0),
        call_quote("2026-07-15", 120, 6, delta=0.5),
        call_quote("2026-06-15", 125, 7),
        call_quote("2026-07-15", 130, 8, multiplier="10"),
    ]
    service = SingleLegOptionsScreenerScanService(
        FullChainClient(quotes),
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cc",
        "AAPL",
        OptionsScreenerFilters(minimum_annualized_return=0),
        threading.Event(),
    )

    assert [candidate.contract.con_id for candidate in result.candidates] == [2]
    assert result.excluded_contracts == 6
    assert result.warnings[0].category == "excluded_contracts"
    assert result.warnings[0].count == 6


def test_cc_scanner_reports_no_matches_and_propagates_cancellation():
    client = FullChainClient([])
    service = SingleLegOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cc",
        "AAPL",
        OptionsScreenerFilters(),
        threading.Event(),
    )
    service.cancel()

    assert [warning.category for warning in result.warnings] == ["no_matches"]
    assert client.cancelled


def test_cc_quote_refresh_resolves_call_identity_and_current_midpoint():
    client = FullChainClient(
        [call_quote("2026-07-17", 110, 456, bid=1, ask=1.4)]
    )
    service = SingleLegOptionsScreenerScanService(client)

    refreshed = service.refresh_quote(refresh_request(strike=110, right="CALL"))

    assert client.requests[-1][1]["right"] == "C"
    assert refreshed.contract.con_id == 456
    assert refreshed.right == "CALL"
    assert refreshed.midpoint == pytest.approx(1.2)
