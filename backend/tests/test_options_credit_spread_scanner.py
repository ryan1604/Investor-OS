from datetime import date, datetime
import threading
from zoneinfo import ZoneInfo

import pytest

from app.options.client import (
    FullOptionChainSnapshot,
    ScannerOptionContract,
    ScannerOptionQuote,
)
from app.options_screeners.credit_spread import (
    CreditSpreadOptionsScreenerScanService,
)
from app.options_screeners.manager import OptionsScreenerScanManager
from app.options_screeners.single_leg import SingleLegOptionsScreenerScanService
from app.options_screeners.store import OptionsScreenerSettingsStore
from app.schemas import CreditSpreadScreenerFilters


class FullChainClient:
    def __init__(self, quotes_by_right):
        self.quotes_by_right = quotes_by_right
        self.requests = []
        self.cancelled = 0
        self.refresh_quotes = []

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
            contracts=self.quotes_by_right[kwargs["right"]],
        )

    def cancel_scanner(self):
        self.cancelled += 1

    def refresh_option_quote(self, **kwargs):
        self.requests.append(("refresh", kwargs))
        if not self.refresh_quotes:
            from app.options.client import OptionsDataUnavailable

            raise OptionsDataUnavailable("The selected option contract could not be quoted.")
        return self.refresh_quotes.pop(0)


def test_put_spreads_sell_higher_strike_and_buy_exact_lower_width():
    client = FullChainClient(
        {
            "P": [
                quote("P", 95, 1, bid=2.1, ask=2.3, delta=-0.25),
                quote("P", 90, 2, bid=0.9, ask=1.0, delta=-0.10),
                quote("P", 89, 3, bid=0.5, ask=0.6, delta=-0.08),
            ],
        }
    )
    service = CreditSpreadOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cs",
        "AAPL",
        CreditSpreadScreenerFilters(
            strategy_types=["put_credit_spread"],
            spread_widths=[5],
            minimum_annualized_return=0,
        ),
        threading.Event(),
    )

    assert client.requests[0][1]["right"] == "P"
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.strategy == "put_credit_spread"
    assert candidate.short_strike == 95
    assert candidate.long_strike == 90
    assert candidate.short_delta == -0.25
    assert candidate.net_bid == pytest.approx(1.1)
    assert candidate.net_ask == pytest.approx(1.4)
    assert candidate.annualized_return == pytest.approx(
        (1.25 / 3.75) * (365 / 30) * 100
    )
    assert candidate.distance_percentage == pytest.approx(5)


def test_call_spreads_sell_lower_strike_and_buy_exact_higher_width():
    client = FullChainClient(
        {
            "C": [
                quote("C", 105, 1, bid=2.1, ask=2.3, delta=0.25),
                quote("C", 110, 2, bid=0.9, ask=1.0, delta=0.10),
            ],
        }
    )
    service = CreditSpreadOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cs",
        "AAPL",
        CreditSpreadScreenerFilters(
            strategy_types=["call_credit_spread"],
            spread_widths=[5],
            minimum_annualized_return=0,
        ),
        threading.Event(),
    )

    assert client.requests[0][1]["right"] == "C"
    assert len(result.candidates) == 1
    assert result.candidates[0].short_strike == 105
    assert result.candidates[0].long_strike == 110
    assert result.candidates[0].distance_percentage == pytest.approx(5)


def test_multiple_strategy_types_and_widths_scan_each_chain_once():
    client = FullChainClient(
        {
            "P": [
                quote("P", 95, 1, bid=2.1, ask=2.3, delta=-0.25),
                quote("P", 90, 2, bid=0.9, ask=1.0, delta=-0.10),
                quote("P", 93, 3, bid=1.5, ask=1.7, delta=-0.20),
            ],
            "C": [
                quote("C", 105, 4, bid=2.1, ask=2.3, delta=0.25),
                quote("C", 110, 5, bid=0.9, ask=1.0, delta=0.10),
            ],
        }
    )
    service = CreditSpreadOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cs",
        "AAPL",
        CreditSpreadScreenerFilters(
            strategy_types=["put_credit_spread", "call_credit_spread"],
            spread_widths=[2, 5],
            minimum_annualized_return=0,
        ),
        threading.Event(),
    )

    assert [request[1]["right"] for request in client.requests] == ["P", "C"]
    assert {(item.strategy, item.short_strike, item.long_strike) for item in result.candidates} == {
        ("put_credit_spread", 95, 90),
        ("put_credit_spread", 95, 93),
        ("call_credit_spread", 105, 110),
    }


def test_spread_scanner_excludes_invalid_net_markets_and_non_short_delta_matches():
    client = FullChainClient(
        {
            "P": [
                quote("P", 95, 1, bid=1.0, ask=1.1, delta=-0.20),
                quote("P", 90, 2, bid=0.9, ask=1.0, delta=-0.60),
                quote("P", 85, 3, bid=0.1, ask=0.2, delta=-0.02),
                quote("P", 80, 4, bid=0.05, ask=0.1, delta=-0.02),
            ],
        }
    )
    service = CreditSpreadOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cs",
        "AAPL",
        CreditSpreadScreenerFilters(
            strategy_types=["put_credit_spread"],
            spread_widths=[5],
            minimum_annualized_return=0,
        ),
        threading.Event(),
    )

    assert result.candidates == []
    assert result.warnings[0].category == "excluded_contracts"


def test_spread_scanner_does_not_require_long_leg_delta():
    client = FullChainClient(
        {
            "P": [
                quote("P", 95, 1, bid=2.1, ask=2.3, delta=-0.25),
                quote("P", 90, 2, bid=0.9, ask=1.0, delta=None),
            ],
        }
    )
    service = CreditSpreadOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cs",
        "AAPL",
        CreditSpreadScreenerFilters(
            strategy_types=["put_credit_spread"],
            spread_widths=[5],
            minimum_annualized_return=0,
        ),
        threading.Event(),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].short_delta == -0.25


def test_spread_scanner_deduplicates_economic_spreads_across_exchanges():
    client = FullChainClient(
        {
            "C": [
                quote("C", 105, 1, exchange="CBOE", bid=2.1, ask=2.3, delta=0.25),
                quote("C", 105, 2, exchange="SMART", bid=2.1, ask=2.3, delta=0.25),
                quote("C", 110, 3, exchange="SMART", bid=0.9, ask=1.0, delta=0.10),
            ],
        }
    )
    service = CreditSpreadOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cs",
        "AAPL",
        CreditSpreadScreenerFilters(
            strategy_types=["call_credit_spread"],
            spread_widths=[5],
            minimum_annualized_return=0,
        ),
        threading.Event(),
    )

    assert [item.short_contract.con_id for item in result.candidates] == [2]
    assert result.excluded_contracts == 2


def test_spread_scanner_keeps_compatible_trading_class_before_deduplicating():
    client = FullChainClient(
        {
            "P": [
                quote(
                    "P",
                    95,
                    1,
                    bid=2.1,
                    ask=2.3,
                    delta=-0.25,
                    trading_class="AAPL",
                ),
                quote(
                    "P",
                    95,
                    2,
                    exchange="CBOE",
                    bid=2.1,
                    ask=2.3,
                    delta=-0.25,
                    trading_class="AAPLW",
                ),
                quote(
                    "P",
                    90,
                    3,
                    exchange="CBOE",
                    bid=0.9,
                    ask=1.0,
                    delta=-0.10,
                    trading_class="AAPLW",
                ),
            ],
        }
    )
    service = CreditSpreadOptionsScreenerScanService(
        client,
        current_date_provider=lambda: date(2026, 6, 15),
    )

    result = service.scan_ticker(
        "cs",
        "AAPL",
        CreditSpreadScreenerFilters(
            strategy_types=["put_credit_spread"],
            spread_widths=[5],
            minimum_annualized_return=0,
        ),
        threading.Event(),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].short_contract.con_id == 2
    assert result.candidates[0].long_contract.con_id == 3


def test_scan_manager_shutdown_cancels_direct_screener_services_once(tmp_path):
    client = FullChainClient({"P": [], "C": []})
    single_leg = SingleLegOptionsScreenerScanService(client)
    credit_spread = CreditSpreadOptionsScreenerScanService(client)
    manager = OptionsScreenerScanManager(
        OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3"),
        {"csp": single_leg, "cc": single_leg, "cs": credit_spread},
        single_leg,
        credit_spread,
    )

    manager.shutdown()

    assert client.cancelled == 2


def test_spread_quote_refresh_resolves_both_legs_and_returns_net_market():
    client = FullChainClient({"P": [], "C": []})
    client.refresh_quotes = [
        quote("P", 95, 1, bid=2.1, ask=2.3, delta=-0.25),
        quote("P", 90, 2, bid=0.9, ask=1.0, delta=None),
    ]
    service = CreditSpreadOptionsScreenerScanService(client)

    refreshed = service.refresh_spread_quote(
        spread_request("put_credit_spread", short_strike=95, long_strike=90)
    )

    assert [request[1]["right"] for request in client.requests] == ["P", "P"]
    assert refreshed.right == "PUT"
    assert refreshed.short_contract.con_id == 1
    assert refreshed.long_contract.con_id == 2
    assert refreshed.net_bid == pytest.approx(1.1)
    assert refreshed.net_ask == pytest.approx(1.4)
    assert refreshed.net_midpoint == pytest.approx(1.25)
    assert refreshed.maximum_loss == pytest.approx(3.75)


def test_call_spread_quote_refresh_uses_call_side_and_signed_width_order():
    client = FullChainClient({"P": [], "C": []})
    client.refresh_quotes = [
        quote("C", 105, 1, bid=2.1, ask=2.3, delta=0.25),
        quote("C", 110, 2, bid=0.9, ask=1.0, delta=None),
    ]
    service = CreditSpreadOptionsScreenerScanService(client)

    refreshed = service.refresh_spread_quote(
        spread_request("call_credit_spread", short_strike=105, long_strike=110)
    )

    assert [request[1]["right"] for request in client.requests] == ["C", "C"]
    assert refreshed.right == "CALL"
    assert refreshed.short_strike == 105
    assert refreshed.long_strike == 110


def test_spread_quote_refresh_blocks_unresolved_or_invalid_net_market():
    client = FullChainClient({"P": [], "C": []})
    client.refresh_quotes = [
        quote("P", 95, 1, bid=1.0, ask=1.1, delta=-0.25),
        quote("P", 90, 2, bid=0.9, ask=1.0, delta=None),
    ]
    service = CreditSpreadOptionsScreenerScanService(client)

    from app.options_screeners.service import OptionsScreenerServiceUnavailable

    with pytest.raises(OptionsScreenerServiceUnavailable):
        service.refresh_spread_quote(
            spread_request("put_credit_spread", short_strike=95, long_strike=90)
        )

    empty_client = FullChainClient({"P": [], "C": []})
    with pytest.raises(OptionsScreenerServiceUnavailable):
        CreditSpreadOptionsScreenerScanService(empty_client).refresh_spread_quote(
            spread_request("put_credit_spread", short_strike=95, long_strike=90)
        )


def contract(
    right,
    strike,
    con_id,
    *,
    expiration="2026-07-15",
    exchange="SMART",
    multiplier="100",
    trading_class="AAPL",
):
    return ScannerOptionContract(
        con_id=con_id,
        ticker="AAPL",
        expiration=expiration,
        strike=strike,
        right=right,
        exchange=exchange,
        currency="USD",
        multiplier=multiplier,
        trading_class=trading_class,
        local_symbol=f"AAPL {expiration} {strike} {right}",
    )


def quote(
    right,
    strike,
    con_id,
    *,
    expiration="2026-07-15",
    exchange="SMART",
    multiplier="100",
    trading_class="AAPL",
    bid=1,
    ask=1.1,
    delta=0.2,
):
    return ScannerOptionQuote(
        contract=contract(
            right,
            strike,
            con_id,
            expiration=expiration,
            exchange=exchange,
            multiplier=multiplier,
            trading_class=trading_class,
        ),
        bid=bid,
        ask=ask,
        delta=delta,
    )


def spread_request(strategy, *, short_strike, long_strike):
    from app.schemas import OptionsScreenerSpreadQuoteRefreshRequest

    return OptionsScreenerSpreadQuoteRefreshRequest(
        strategy=strategy,
        ticker="AAPL",
        expiration="2026-07-15",
        short_strike=short_strike,
        long_strike=long_strike,
        short_contract={"con_id": 1, "local_symbol": "AAPL SHORT"},
        long_contract={"con_id": 2, "local_symbol": "AAPL LONG"},
    )
