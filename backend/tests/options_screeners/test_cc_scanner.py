from datetime import date
import threading

import pytest

from app.options.client import OptionsClient
from app.options.store import OptionsDailyBarStore
from app.options_screeners.single_leg import SingleLegOptionsScreenerScanService
from app.schemas import (
    OptionsScreenerFilters,
)
from tests.options_screeners.helpers import (
    HistoricalProvider,
    MetadataProvider,
    ScannerProvider,
    EmptyProvider,
    FullChainClient,
    call_quote,
    put_quote,
    refresh_request,
)


def test_full_call_chain_scans_every_otm_strike_and_inclusive_expiration(
    tmp_path,
):
    historical = HistoricalProvider()
    scanner = ScannerProvider(right="C", ask=1.2, delta=0.2)
    empty = EmptyProvider()
    client = OptionsClient(
        OptionsDailyBarStore(tmp_path / "options.sqlite3"),
        historical,
        MetadataProvider(strikes=[95, 100, 105, 110, 115]),
        empty,
        empty,
        empty,
        scanner_provider=scanner,
        current_date_provider=lambda: date(2026, 6, 15),
        max_chain_stream_strikes=80,
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
        [
            (expiration, strike)
            for expiration in ["2026-06-22", "2026-06-26", "2026-07-30"]
            for strike in [105, 110, 115]
        ],
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
