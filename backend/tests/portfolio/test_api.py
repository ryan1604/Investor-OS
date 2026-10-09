import time

from fastapi.testclient import TestClient

from app.portfolio.service import get_portfolio_response
from tests.conftest import FakePortfolioClient, make_api


def test_portfolio_snapshot_log_contains_counts_without_sensitive_values(caplog):
    portfolio_client = FakePortfolioClient(connected=True)

    with caplog.at_level("INFO", logger="app.portfolio.service"):
        response = get_portfolio_response(portfolio_client)

    assert response.positions[0].symbol == "AAPL"
    assert "Portfolio snapshot refreshed accounts=1 positions=1 total_ms=" in caplog.text
    assert "DU1234567" not in caplog.text
    assert "AAPL" not in caplog.text
    assert "125000" not in caplog.text


def test_portfolio_returns_empty_cached_snapshot_before_first_refresh():
    portfolio_client = FakePortfolioClient(connected=True, block_refresh=True)
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        assert portfolio_client.refresh_started.wait(timeout=1)
        positions_requests_before_get = portfolio_client.positions_requests
        response = client.get("/portfolio")
        positions_requests_after_get = portfolio_client.positions_requests
        portfolio_client.allow_refresh.set()

    assert response.status_code == 200
    assert response.json()["status"]["connected"] is True
    assert response.json()["accounts"] == []
    assert response.json()["positions"] == []
    assert response.json()["message"] == "Portfolio data has not loaded yet."
    assert positions_requests_before_get == 1
    assert positions_requests_after_get == positions_requests_before_get
    assert portfolio_client.stopped is True
    assert api.state.portfolio_refresh_service.task is None


def test_portfolio_returns_empty_state_when_disconnected():
    api = make_api(FakePortfolioClient(connected=False))

    with TestClient(api) as client:
        response = client.get("/portfolio")

    assert response.status_code == 200
    assert response.json()["status"]["connected"] is False
    assert response.json()["accounts"] == []
    assert response.json()["positions"] == []
    assert response.json()["message"] == "Interactive Brokers is not connected."


def test_portfolio_websocket_streams_positions_when_connected():
    portfolio_client = FakePortfolioClient(connected=True, block_refresh=True)
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        with client.websocket_connect("/portfolio/ws") as websocket:
            cached_payload = websocket.receive_json()
            portfolio_client.allow_refresh.set()
            refreshed_payload = websocket.receive_json()

    assert cached_payload["status"]["connected"] is True
    assert cached_payload["accounts"] == []
    assert cached_payload["positions"] == []
    assert cached_payload["message"] == "Portfolio data has not loaded yet."
    assert refreshed_payload["accounts"][0]["buying_power"] == 468_000
    assert refreshed_payload["accounts"][0]["cash_total_sgd"] == 10_000
    assert refreshed_payload["accounts"][0]["cash_total_usd"] == 20_000
    assert refreshed_payload["accounts"][0]["cash_total"] == 35_000
    assert refreshed_payload["positions"][0]["symbol"] == "AAPL"
    assert refreshed_payload["message"] == "Loaded 1 position(s) from Interactive Brokers."


def test_portfolio_returns_cached_websocket_refresh():
    portfolio_client = FakePortfolioClient(connected=True, block_refresh=True)
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        with client.websocket_connect("/portfolio/ws") as websocket:
            websocket.receive_json()
            portfolio_client.allow_refresh.set()
            websocket.receive_json()

        response = client.get("/portfolio")

    assert response.status_code == 200
    assert response.json()["accounts"][0]["net_liquidation"] == 125_000
    assert response.json()["accounts"][0]["daily_pnl_percent"] == 0.36
    assert response.json()["positions"][0]["symbol"] == "AAPL"
    assert response.json()["message"] == "Loaded 1 position(s) from Interactive Brokers."
    assert portfolio_client.positions_requests == 1


def test_portfolio_websockets_share_one_refresh_loop():
    portfolio_client = FakePortfolioClient(connected=True, block_refresh=True)
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        with (
            client.websocket_connect("/portfolio/ws") as first_websocket,
            client.websocket_connect("/portfolio/ws") as second_websocket,
        ):
            first_websocket.receive_json()
            second_websocket.receive_json()
            portfolio_client.allow_refresh.set()
            first_payload = first_websocket.receive_json()
            second_payload = second_websocket.receive_json()

    assert first_payload["positions"][0]["symbol"] == "AAPL"
    assert second_payload["positions"][0]["symbol"] == "AAPL"
    assert portfolio_client.positions_requests == 1


def test_portfolio_quote_websocket_holds_position_quotes_while_open():
    portfolio_client = FakePortfolioClient(connected=True)
    api = make_api(portfolio_client)

    with TestClient(api) as client:
        with (
            client.websocket_connect("/portfolio/quotes/ws"),
            client.websocket_connect("/portfolio/quotes/ws"),
        ):
            wait_for(lambda: portfolio_client.quote_viewers == 2)
        wait_for(lambda: portfolio_client.quote_viewers == 0)


def wait_for(predicate, timeout_seconds: float = 1) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()
