import threading

from fastapi.testclient import TestClient

from app.main import create_app
from app.options.client import OptionsDataUnavailable
from app.schemas import (
    BollingerBandPoint,
    IbStatus,
    OptionChainLiveMessage,
    OptionChainResponse,
    OptionChainRow,
    OptionDailyBar,
    OptionExpiration,
    OptionExpirationsResponse,
    OptionQuote,
    OptionsAnalysisResponse,
    OptionsChartLiveMessage,
    RsiPoint,
)


class FakePortfolioClient:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def get_status(self) -> IbStatus:
        return IbStatus(
            connected=False,
            host="127.0.0.1",
            port=7497,
            client_id=1,
        )

    def refresh_account_summaries(self) -> None:
        return None


class FakeOptionsAnalysisClient:
    def __init__(self) -> None:
        self.stream_stop_events: list[threading.Event] = []
        self.chart_stream_stop_events: list[threading.Event] = []

    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
        if ticker == "missing":
            raise OptionsDataUnavailable("No options analysis data is available.")

        return OptionsAnalysisResponse(
            ticker=ticker.upper(),
            underlying_price=102,
            candles=[
                OptionDailyBar(
                    date="2026-05-29",
                    open=100,
                    high=103,
                    low=99,
                    close=102,
                    volume=1_000,
                )
            ],
            bollinger_bands=[
                BollingerBandPoint(
                    date="2026-05-29",
                    upper=None,
                    middle=None,
                    lower=None,
                )
            ],
            rsi=[RsiPoint(date="2026-05-29", value=None)],
            message="Loaded analysis data for AAPL.",
        )

    def get_expirations(self, ticker: str) -> OptionExpirationsResponse:
        return OptionExpirationsResponse(
            ticker=ticker.upper(),
            expirations=[OptionExpiration(date="2026-06-19", days_to_expiration=20)],
            selected_expiration="2026-06-19",
            message=f"Loaded expirations for {ticker.upper()}.",
        )

    def get_chain(self, ticker: str, expiration: str) -> OptionChainResponse:
        return OptionChainResponse(
            ticker=ticker.upper(),
            expiration=expiration,
            underlying_price=100,
            rows=[
                OptionChainRow(
                    strike=100,
                    call=OptionQuote(bid=1, ask=1.2, mid=1.1, breakeven=101.2),
                    put=OptionQuote(bid=0.8, ask=1, mid=0.9, breakeven=99),
                )
            ],
            message=f"Loaded 1 strike(s) for {ticker.upper()} {expiration}.",
        )

    def stream_chain(
        self,
        ticker: str,
        expiration: str,
        *,
        stop_event: threading.Event,
    ):
        self.stream_stop_events.append(stop_event)
        yield OptionChainLiveMessage(
            type="snapshot",
            ticker=ticker.upper(),
            expiration=expiration,
            rows=[
                OptionChainRow(
                    strike=100,
                    call=OptionQuote(bid=1, ask=1.2, mid=1.1, breakeven=101.2),
                )
            ],
            message=f"Streaming 1 strike(s) for {ticker.upper()} {expiration}.",
        )
        yield OptionChainLiveMessage(
            type="update",
            ticker=ticker.upper(),
            expiration=expiration,
            row=OptionChainRow(
                strike=100,
                call=OptionQuote(bid=1.1, ask=1.3, mid=1.2, breakeven=101.3),
            ),
        )

    def stream_chart(
        self,
        ticker: str,
        *,
        stop_event: threading.Event,
    ):
        self.chart_stream_stop_events.append(stop_event)
        yield OptionsChartLiveMessage(
            type="update",
            ticker=ticker.upper(),
            candle=OptionDailyBar(
                date="2026-05-30",
                open=102,
                high=104,
                low=101,
                close=103,
                volume=2_000,
            ),
            bollinger_band=BollingerBandPoint(
                date="2026-05-30",
                upper=105,
                middle=102,
                lower=99,
            ),
            rsi=RsiPoint(date="2026-05-30", value=61),
        )


class QuietOptionsAnalysisClient(FakeOptionsAnalysisClient):
    def __init__(self) -> None:
        super().__init__()
        self.chain_stream_started = threading.Event()
        self.chain_stream_cleaned = threading.Event()
        self.chart_stream_started = threading.Event()
        self.chart_stream_cleaned = threading.Event()

    def stream_chain(self, ticker, expiration, *, stop_event):
        self.stream_stop_events.append(stop_event)
        self.chain_stream_started.set()
        try:
            while not stop_event.wait(0.01):
                pass
            if False:
                yield None
        finally:
            self.chain_stream_cleaned.set()

    def stream_chart(self, ticker, *, stop_event):
        self.chart_stream_stop_events.append(stop_event)
        self.chart_stream_started.set()
        try:
            while not stop_event.wait(0.01):
                pass
            if False:
                yield None
        finally:
            self.chart_stream_cleaned.set()


def test_options_analysis_returns_chart_ready_payload():
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: FakeOptionsAnalysisClient(),
    )

    with TestClient(api) as client:
        response = client.get("/options/aapl/analysis")

    assert response.status_code == 200
    assert response.json() == {
        "ticker": "AAPL",
        "underlying_price": 102,
        "candles": [
            {
                "date": "2026-05-29",
                "open": 100,
                "high": 103,
                "low": 99,
                "close": 102,
                "volume": 1_000,
            }
        ],
        "bollinger_bands": [
            {
                "date": "2026-05-29",
                "upper": None,
                "middle": None,
                "lower": None,
            }
        ],
        "rsi": [{"date": "2026-05-29", "value": None}],
        "message": "Loaded analysis data for AAPL.",
    }


def test_option_expirations_returns_selection_payload():
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: FakeOptionsAnalysisClient(),
    )

    with TestClient(api) as client:
        response = client.get("/options/aapl/expirations")

    assert response.status_code == 200
    assert response.json() == {
        "ticker": "AAPL",
        "expirations": [{"date": "2026-06-19", "days_to_expiration": 20}],
        "selected_expiration": "2026-06-19",
        "message": "Loaded expirations for AAPL.",
    }


def test_options_analysis_returns_clear_error_for_unknown_ticker():
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: FakeOptionsAnalysisClient(),
    )

    with TestClient(api) as client:
        response = client.get("/options/missing/analysis")

    assert response.status_code == 404
    assert response.json() == {"detail": "No options analysis data is available."}


def test_options_analysis_returns_clear_error_without_provider_wiring():
    api = create_app(lambda _settings: FakePortfolioClient())

    with TestClient(api) as client:
        response = client.get("/options/aapl/analysis")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Options historical data provider is not configured.",
    }


def test_option_chain_returns_quote_rows_for_selected_expiration():
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: FakeOptionsAnalysisClient(),
    )

    with TestClient(api) as client:
        response = client.get("/options/msft/chain?expiration=2026-06-19")

    assert response.status_code == 200
    assert response.json() == {
        "ticker": "MSFT",
        "expiration": "2026-06-19",
        "underlying_price": 100,
        "rows": [
            {
                "strike": 100,
                "call": {
                    "local_symbol": None,
                        "delta": None,
                        "bid": 1,
                        "bid_size": None,
                        "ask": 1.2,
                        "ask_size": None,
                    "mid": 1.1,
                    "last": None,
                    "close": None,
                    "model_price": None,
                    "change_percent": None,
                    "volume": None,
                    "open_interest": None,
                    "gamma": None,
                    "theta": None,
                    "implied_volatility_percent": None,
                    "breakeven": 101.2,
                },
                "put": {
                    "local_symbol": None,
                        "delta": None,
                        "bid": 0.8,
                        "bid_size": None,
                        "ask": 1,
                        "ask_size": None,
                    "mid": 0.9,
                    "last": None,
                    "close": None,
                    "model_price": None,
                    "change_percent": None,
                    "volume": None,
                    "open_interest": None,
                    "gamma": None,
                    "theta": None,
                    "implied_volatility_percent": None,
                    "breakeven": 99,
                },
            }
        ],
        "message": "Loaded 1 strike(s) for MSFT 2026-06-19.",
    }


def test_option_chain_websocket_streams_snapshot_and_updates():
    fake_options_client = FakeOptionsAnalysisClient()
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: fake_options_client,
    )

    with TestClient(api) as client:
        with client.websocket_connect(
            "/options/tsla/chain/ws?expiration=2026-06-19",
        ) as websocket:
            snapshot = websocket.receive_json()
            update = websocket.receive_json()

    assert snapshot == {
        "type": "snapshot",
        "ticker": "TSLA",
        "expiration": "2026-06-19",
        "rows": [
            {
                "strike": 100,
                "call": {
                    "local_symbol": None,
                        "delta": None,
                        "bid": 1,
                        "bid_size": None,
                        "ask": 1.2,
                        "ask_size": None,
                    "mid": 1.1,
                    "last": None,
                    "close": None,
                    "model_price": None,
                    "change_percent": None,
                    "volume": None,
                    "open_interest": None,
                    "gamma": None,
                    "theta": None,
                    "implied_volatility_percent": None,
                    "breakeven": 101.2,
                },
                "put": None,
            }
        ],
        "row": None,
        "message": "Streaming 1 strike(s) for TSLA 2026-06-19.",
    }
    assert update["type"] == "update"
    assert update["ticker"] == "TSLA"
    assert update["expiration"] == "2026-06-19"
    assert update["rows"] is None
    assert update["row"]["call"]["bid"] == 1.1
    assert fake_options_client.stream_stop_events[0].is_set()


def test_options_chart_websocket_streams_candle_and_indicator_update():
    fake_options_client = FakeOptionsAnalysisClient()
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: fake_options_client,
    )

    with TestClient(api) as client:
        with client.websocket_connect("/options/aapl/chart/ws") as websocket:
            update = websocket.receive_json()

    assert update == {
        "type": "update",
        "ticker": "AAPL",
        "candle": {
            "date": "2026-05-30",
            "open": 102,
            "high": 104,
            "low": 101,
            "close": 103,
            "volume": 2_000,
        },
        "bollinger_band": {
            "date": "2026-05-30",
            "upper": 105,
            "middle": 102,
            "lower": 99,
        },
        "rsi": {"date": "2026-05-30", "value": 61},
    }
    assert fake_options_client.chart_stream_stop_events[0].is_set()


def test_quiet_option_chain_websocket_disconnect_stops_stream():
    fake_options_client = QuietOptionsAnalysisClient()
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: fake_options_client,
    )

    with TestClient(api) as client:
        with client.websocket_connect(
            "/options/aapl/chain/ws?expiration=2026-06-19",
        ):
            assert fake_options_client.chain_stream_started.wait(1)

    assert fake_options_client.chain_stream_cleaned.wait(1)
    assert fake_options_client.stream_stop_events[0].is_set()


def test_quiet_options_chart_websocket_disconnect_stops_stream():
    fake_options_client = QuietOptionsAnalysisClient()
    api = create_app(
        lambda _settings: FakePortfolioClient(),
        lambda _settings, _client: fake_options_client,
    )

    with TestClient(api) as client:
        with client.websocket_connect("/options/aapl/chart/ws"):
            assert fake_options_client.chart_stream_started.wait(1)

    assert fake_options_client.chart_stream_cleaned.wait(1)
    assert fake_options_client.chart_stream_stop_events[0].is_set()
