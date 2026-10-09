import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.options.types import OptionsDataUnavailable
from app.schemas import (
    OptionsAnalysisResponse,
)
from tests.conftest import FakeOptionsAnalysisClient, make_api


class BlockingOptionsAnalysisClient(FakeOptionsAnalysisClient):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.active = 0
        self.lock = threading.Lock()

    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
        with self.lock:
            self.active += 1
            if self.active == 2:
                self.started.set()

        self.release.wait(timeout=2)
        return super().get_analysis(ticker)


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
    api = make_api(options_client=FakeOptionsAnalysisClient())

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
    api = make_api(options_client=FakeOptionsAnalysisClient())

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
    api = make_api(options_client=FakeOptionsAnalysisClient())

    with TestClient(api) as client:
        response = client.get("/options/missing/analysis")

    assert response.status_code == 404
    assert response.json() == {"detail": "No options analysis data is available."}


def test_options_analysis_returns_clear_error_without_provider_wiring():
    api = make_api()

    with TestClient(api) as client:
        response = client.get("/options/aapl/analysis")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Options historical data provider is not configured.",
    }


def test_options_analysis_returns_busy_when_request_limit_is_saturated():
    fake_options_client = BlockingOptionsAnalysisClient()
    api = make_api(options_client=fake_options_client)

    with TestClient(api) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            blocked_requests = [
                executor.submit(client.get, "/options/aapl/analysis")
                for _ in range(2)
            ]
            assert fake_options_client.started.wait(timeout=1)

            busy_response = client.get("/options/aapl/analysis")
            fake_options_client.release.set()
            completed_responses = [future.result(timeout=1) for future in blocked_requests]

    assert busy_response.status_code == 503
    assert busy_response.json() == {
        "detail": "options analysis capacity is temporarily exhausted.",
    }
    assert [response.status_code for response in completed_responses] == [200, 200]


def test_option_chain_returns_quote_rows_for_selected_expiration():
    api = make_api(options_client=FakeOptionsAnalysisClient())

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
    api = make_api(options_client=fake_options_client)

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
        "warning": None,
    }
    assert update["type"] == "update"
    assert update["ticker"] == "TSLA"
    assert update["expiration"] == "2026-06-19"
    assert update["rows"] is None
    assert update["row"]["call"]["bid"] == 1.1
    assert fake_options_client.stream_stop_events[0].is_set()


def test_options_chart_websocket_streams_candle_and_indicator_update():
    fake_options_client = FakeOptionsAnalysisClient()
    api = make_api(options_client=fake_options_client)

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
    api = make_api(options_client=fake_options_client)

    with TestClient(api) as client:
        with client.websocket_connect(
            "/options/aapl/chain/ws?expiration=2026-06-19",
        ):
            assert fake_options_client.chain_stream_started.wait(1)

    assert fake_options_client.chain_stream_cleaned.wait(1)
    assert fake_options_client.stream_stop_events[0].is_set()


def test_quiet_options_chart_websocket_disconnect_stops_stream():
    fake_options_client = QuietOptionsAnalysisClient()
    api = make_api(options_client=fake_options_client)

    with TestClient(api) as client:
        with client.websocket_connect("/options/aapl/chart/ws"):
            assert fake_options_client.chart_stream_started.wait(1)

    assert fake_options_client.chart_stream_cleaned.wait(1)
    assert fake_options_client.chart_stream_stop_events[0].is_set()


@pytest.mark.parametrize(
    ("path", "client_method"),
    [
        ("/options/aapl/chain?expiration=2026-06-19", "get_chain"),
        ("/options/aapl/expirations", "get_expirations"),
    ],
)
def test_options_data_errors_keep_http_status_and_detail(monkeypatch, path, client_method):
    options_client = FakeOptionsAnalysisClient()

    def fail(*_args):
        raise OptionsDataUnavailable("Options data is unavailable.")

    monkeypatch.setattr(options_client, client_method, fail)
    api = make_api(options_client=options_client)
    with TestClient(api) as client:
        response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Options data is unavailable."}


def test_option_chain_websocket_keeps_unavailable_snapshot(monkeypatch):
    options_client = FakeOptionsAnalysisClient()

    def fail(*_args, **_kwargs):
        raise OptionsDataUnavailable("Options data is unavailable.")

    monkeypatch.setattr(options_client, "stream_chain", fail)
    api = make_api(options_client=options_client)
    with TestClient(api) as client:
        with client.websocket_connect(
            "/options/aapl/chain/ws?expiration=2026-06-19",
        ) as websocket:
            snapshot = websocket.receive_json()

    assert snapshot == {
        "type": "snapshot",
        "ticker": "AAPL",
        "expiration": "2026-06-19",
        "rows": [],
        "row": None,
        "message": "Options data is unavailable.",
        "warning": None,
    }


def test_options_chart_websocket_keeps_unavailable_return(monkeypatch):
    options_client = FakeOptionsAnalysisClient()
    started = threading.Event()

    def fail(*_args, **_kwargs):
        started.set()
        raise OptionsDataUnavailable("Options data is unavailable.")

    monkeypatch.setattr(options_client, "stream_chart", fail)
    api = make_api(options_client=options_client)
    with TestClient(api) as client:
        with client.websocket_connect("/options/aapl/chart/ws"):
            assert started.wait(1)
