import threading
from datetime import (
    date,
    datetime,
)
from zoneinfo import ZoneInfo

from app.ib.app import IbPortfolioApp
from app.ib.market_data_lines import MarketDataLineBudget
from app.ib.daily_bars import (
    IbHistoricalDailyBarProvider,
    IbHistoricalDailyBarStreamProvider,
)
from app.options.types import OptionsDataUnavailable
from app.options.store import CompletedDailyBar
from tests.conftest import FakeIbAppBase


class FakeHistoricalIbApp(FakeIbAppBase):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.next_historical_req_id = 60_000
        self.historical_bars: dict[int, list[CompletedDailyBar]] = {}
        self.historical_req_tickers: dict[int, str] = {}
        self.historical_data_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.requests = []

    def isConnected(self) -> bool:
        return True

    def reqHistoricalData(
        self,
        req_id,
        contract,
        end_date_time,
        duration,
        bar_size,
        what_to_show,
        use_rth,
        format_date,
        keep_up_to_date,
        chart_options,
    ) -> None:
        self.requests.append(
            (
                req_id,
                contract,
                end_date_time,
                duration,
                bar_size,
                what_to_show,
                use_rth,
                format_date,
                keep_up_to_date,
                chart_options,
            )
        )
        self.historical_bars[req_id] = [
            CompletedDailyBar(
                ticker=contract.symbol,
                trading_date="2026-05-29",
                open=100,
                high=101,
                low=99,
                close=100,
            )
        ]
        self.historical_data_ready_by_req_id[req_id].set()


class InvalidTickerHistoricalIbApp(FakeHistoricalIbApp):
    def reqHistoricalData(self, req_id, contract, *args) -> None:
        self.requests.append((req_id, contract, *args))
        self.request_errors_by_req_id[req_id] = (
            200,
            "No security definition has been found for the request",
        )
        self.historical_data_ready_by_req_id[req_id].set()


def test_ib_historical_provider_requests_daily_trade_bars_for_us_equity():
    app = FakeHistoricalIbApp()
    provider = IbHistoricalDailyBarProvider(app)

    bars = provider.fetch_daily_bars(
        "amd",
        date(2026, 5, 1),
        date(2026, 5, 30),
    )

    request = app.requests[0]
    requested_contract = request[1]
    assert requested_contract.symbol == "AMD"
    assert requested_contract.secType == "STK"
    assert requested_contract.exchange == "SMART"
    assert requested_contract.currency == "USD"
    assert request[2] == "20260530 23:59:59 US/Eastern"
    assert request[3] == "30 D"
    assert request[4] == "1 day"
    assert request[5] == "TRADES"
    assert bars[0].trading_date == "2026-05-29"


def test_ib_historical_provider_rejects_invalid_ticker_without_waiting_for_chunks():
    app = InvalidTickerHistoricalIbApp()
    provider = IbHistoricalDailyBarProvider(app)

    try:
        provider.fetch_daily_bars(
            "invalid",
            date(2016, 5, 30),
            date(2017, 5, 29),
        )
    except OptionsDataUnavailable as error:
        assert str(error) == "Invalid ticker: INVALID."
    else:
        raise AssertionError("Expected invalid ticker to be rejected.")

    assert len(app.requests) == 1
    assert app.historical_bars == {}
    assert app.historical_req_tickers == {}
    assert app.historical_data_ready_by_req_id == {}
    assert app.request_errors_by_req_id == {}


class FakeHistoricalStreamIbApp(FakeIbAppBase):
    def __init__(self, *, primary_exchange: str = "NASDAQ") -> None:
        super().__init__()
        self.primary_exchange = primary_exchange
        self.lock = threading.Lock()
        self.next_historical_req_id = 60_000
        self.next_chart_market_req_id = 110_000
        self.next_contract_details_req_id = 70_000
        self.historical_bars: dict[int, list[CompletedDailyBar]] = {}
        self.historical_req_tickers: dict[int, str] = {}
        self.historical_data_ready_by_req_id: dict[int, threading.Event] = {}
        self.chart_market_req_tickers: dict[int, str] = {}
        self.chart_market_updates_by_req_id: dict[int, list[CompletedDailyBar]] = {}
        self.chart_market_ready_by_req_id: dict[int, threading.Event] = {}
        self.contract_details = {}
        self.contract_details_ready_by_req_id: dict[int, threading.Event] = {}
        self.request_errors_by_req_id: dict[int, tuple[int, str]] = {}
        self.historical_requests = []
        self.contract_detail_requests = []
        self.market_requests = []
        self.market_data_types = []
        self.cancelled_historical_data = []
        self.cancelled_market_data = []

    def isConnected(self) -> bool:
        return True

    def reqHistoricalData(self, req_id, contract, *args) -> None:
        self.historical_requests.append((req_id, contract, *args))
        self.historical_bars[req_id] = [
            CompletedDailyBar(
                ticker=contract.symbol,
                trading_date="2026-05-30",
                open=100,
                high=102,
                low=99,
                close=101,
            )
        ]
        self.historical_data_ready_by_req_id[req_id].set()

    def reqContractDetails(self, req_id, contract) -> None:
        contract.primaryExchange = self.primary_exchange
        self.contract_detail_requests.append((req_id, contract))
        self.contract_details[req_id] = [
            type("ContractDetails", (), {"contract": contract})(),
        ]
        self.contract_details_ready_by_req_id[req_id].set()

    def reqMarketDataType(self, market_data_type: int) -> None:
        self.market_data_types.append(market_data_type)

    def reqMktData(self, req_id, contract, *args) -> None:
        self.market_requests.append((req_id, contract, *args))
        self.chart_market_updates_by_req_id[req_id] = [
            CompletedDailyBar(
                ticker=contract.symbol,
                trading_date="2026-05-30",
                open=101,
                high=103,
                low=100,
                close=102,
            )
        ]
        self.chart_market_ready_by_req_id[req_id].set()

    def cancelHistoricalData(self, req_id: int) -> None:
        self.cancelled_historical_data.append(req_id)

    def cancelMktData(self, req_id: int) -> None:
        self.cancelled_market_data.append(req_id)


def test_ib_historical_stream_provider_aggregates_direct_market_ticks_and_cleans_up():
    app = FakeHistoricalStreamIbApp()
    provider = IbHistoricalDailyBarStreamProvider(app, wait_seconds=0.01)
    stream = provider.stream_daily_bar_updates("aapl", threading.Event())

    initial_bar = next(stream)
    updated_bar = next(stream)
    stream.close()

    historical_request = app.historical_requests[0]
    market_request = app.market_requests[0]
    assert historical_request[1].symbol == "AAPL"
    assert historical_request[3:] == (
        "2 D",
        "1 day",
        "TRADES",
        1,
        1,
        False,
        [],
    )
    assert market_request[1].symbol == "AAPL"
    assert market_request[1].exchange == "NASDAQ"
    assert market_request[2:] == ("", False, False, [])
    assert app.market_data_types == [3]
    assert initial_bar.close == 101
    assert updated_bar == CompletedDailyBar(
        ticker="AAPL",
        trading_date="2026-05-30",
        open=100,
        high=103,
        low=99,
        close=102,
        volume=None,
    )
    assert app.cancelled_historical_data == []
    assert app.cancelled_market_data == [110_000]
    assert app.historical_bars == {}
    assert app.historical_req_tickers == {}
    assert app.historical_data_ready_by_req_id == {}
    assert app.chart_market_req_tickers == {}
    assert app.chart_market_updates_by_req_id == {}
    assert app.chart_market_ready_by_req_id == {}


def test_ib_historical_stream_provider_requires_primary_exchange():
    app = FakeHistoricalStreamIbApp(primary_exchange="")
    provider = IbHistoricalDailyBarStreamProvider(app)
    stream = provider.stream_daily_bar_updates("aapl", threading.Event())

    try:
        next(stream)
    except OptionsDataUnavailable as error:
        assert str(error) == "Primary market-data exchange is unavailable for AAPL."
    else:
        raise AssertionError("Expected missing primary exchange to be rejected.")

    assert app.market_requests == []


class FakeBar:
    date = "20260529"
    open = 100
    high = 101
    low = 99
    close = 100.5
    volume = 1234


def test_ib_app_historical_data_callback_records_completed_daily_bar():
    app = IbPortfolioApp()
    app.historical_req_tickers[60_000] = "AAPL"
    ready = threading.Event()
    app.historical_data_ready_by_req_id[60_000] = ready

    app.historicalData(60_000, FakeBar())
    app.historicalDataEnd(60_000, "", "")

    assert app.historical_bars[60_000] == [
        CompletedDailyBar(
            ticker="AAPL",
            trading_date="2026-05-29",
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=1234,
        )
    ]
    assert ready.is_set()


def test_ib_app_initial_historical_callback_feeds_live_subscription():
    app = IbPortfolioApp()
    ready = threading.Event()
    app.historical_update_req_tickers[60_000] = "AAPL"
    app.historical_updates_by_req_id[60_000] = []
    app.historical_update_ready_by_req_id[60_000] = ready

    app.historicalData(60_000, FakeBar())

    assert app.historical_updates_by_req_id[60_000] == [
        CompletedDailyBar(
            ticker="AAPL",
            trading_date="2026-05-29",
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=1234,
        )
    ]
    assert ready.is_set()


def test_ib_app_initial_historical_callback_ignores_invalid_live_bar():
    class InvalidDateBar(FakeBar):
        date = "invalid"

    app = IbPortfolioApp()
    ready = threading.Event()
    app.historical_update_req_tickers[60_000] = "AAPL"
    app.historical_updates_by_req_id[60_000] = []
    app.historical_update_ready_by_req_id[60_000] = ready

    app.historicalData(60_000, InvalidDateBar())

    assert app.historical_updates_by_req_id[60_000] == []
    assert not ready.is_set()


def test_ib_app_historical_update_callback_isolates_live_ticker():
    app = IbPortfolioApp()
    ready = threading.Event()
    other_ready = threading.Event()
    app.historical_update_req_tickers = {
        60_000: "AAPL",
        60_001: "MSFT",
    }
    app.historical_updates_by_req_id = {60_000: [], 60_001: []}
    app.historical_update_ready_by_req_id = {
        60_000: ready,
        60_001: other_ready,
    }

    app.historicalDataUpdate(60_000, FakeBar())

    assert app.historical_updates_by_req_id[60_000][0].ticker == "AAPL"
    assert app.historical_updates_by_req_id[60_001] == []
    assert ready.is_set()
    assert not other_ready.is_set()


def test_ib_app_chart_market_tick_callback_isolates_live_ticker():
    app = IbPortfolioApp()
    ready = threading.Event()
    other_ready = threading.Event()
    app.chart_market_req_tickers = {
        110_000: "AAPL",
        110_001: "MSFT",
    }
    app.chart_market_updates_by_req_id = {110_000: [], 110_001: []}
    app.chart_market_ready_by_req_id = {
        110_000: ready,
        110_001: other_ready,
    }

    app.tickPrice(110_000, 68, 101, None)

    assert app.chart_market_updates_by_req_id[110_000] == [
        CompletedDailyBar(
            ticker="AAPL",
            trading_date=datetime.now(
                ZoneInfo("America/New_York"),
            ).date().isoformat(),
            open=101,
            high=101,
            low=101,
            close=101,
        )
    ]
    assert app.chart_market_updates_by_req_id[110_001] == []
    assert ready.is_set()
    assert not other_ready.is_set()


def test_ib_chart_stream_holds_one_budget_line_until_closed():
    app = FakeHistoricalStreamIbApp()
    app.market_data_lines = MarketDataLineBudget(1)
    stop_event = threading.Event()
    provider = IbHistoricalDailyBarStreamProvider(app, wait_seconds=0.01)
    stream = provider.stream_daily_bar_updates("aapl", stop_event)

    next(stream)
    assert app.market_data_lines.usage_by_group() == {"chart": 1}
    stop_event.set()
    stream.close()

    assert app.market_data_lines.used() == 0