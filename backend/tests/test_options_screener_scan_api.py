import threading
import time

from fastapi.testclient import TestClient

from app.schemas import (
    CashSecuredPutCandidate,
    OptionContractIdentity,
    OptionsScreenerQuoteRefreshResponse,
    OptionsScreenerSpreadQuoteRefreshResponse,
)
from app.options_screeners.service import OptionsScreenerTickerResult
from conftest import make_api


class ApiScanService:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.results = {}
        self.prepare_error = None
        self.cancel_calls = 0

    def prepare_scan(self, screener, tickers, filters, cancel_event):
        if self.prepare_error is not None:
            error = self.prepare_error
            self.prepare_error = None
            raise error

    def scan_ticker(self, screener, ticker, filters, cancel_event):
        self.started.set()
        while not self.release.wait(0.01):
            if cancel_event.is_set():
                return OptionsScreenerTickerResult()
        return self.results.get(ticker, OptionsScreenerTickerResult())

    def cancel(self):
        self.cancel_calls += 1
        self.release.set()

    def refresh_quote(self, request):
        return OptionsScreenerQuoteRefreshResponse(
            **request.model_dump(),
            bid=1,
            ask=1.2,
            midpoint=1.1,
            delta=-0.2,
            refreshed_at="2026-06-14T00:00:00+00:00",
        )

    def refresh_spread_quote(self, request):
        return OptionsScreenerSpreadQuoteRefreshResponse(
            **request.model_dump(),
            right="PUT",
            short_bid=2.1,
            short_ask=2.3,
            short_midpoint=2.2,
            long_bid=0.9,
            long_ask=1.0,
            long_midpoint=0.95,
            short_delta=-0.2,
            net_bid=1.1,
            net_ask=1.4,
            net_midpoint=1.25,
            maximum_loss=3.75,
            refreshed_at="2026-06-14T00:00:00+00:00",
        )


def test_scan_api_supports_conflict_recovery_cancellation_and_snapshots(tmp_path):
    service = ApiScanService()
    service.release.clear()
    api = scan_api(tmp_path, service)

    with TestClient(api) as client:
        client.put(
            "/options-screeners/settings/ticker-lists/csp_cc",
            json={"tickers": ["AAPL", "MSFT"]},
        )
        start = client.post("/options-screeners/scans/csp")
        job_id = start.json()["id"]
        assert service.started.wait(1)

        conflict = client.post("/options-screeners/scans/cc")
        credit_spread_conflict = client.post("/options-screeners/scans/cs")
        recovered = client.get("/options-screeners/state")
        cancel = client.post(f"/options-screeners/scans/{job_id}/cancel")
        terminal = wait_for_api_terminal(client, job_id)
        snapshot = client.get("/options-screeners/snapshots/csp")

    assert start.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["active_job_id"] == job_id
    assert conflict.json()["detail"]["active_screener"] == "csp"
    assert credit_spread_conflict.status_code == 409
    assert credit_spread_conflict.json()["detail"]["active_job_id"] == job_id
    assert recovered.json()["active_job"]["id"] == job_id
    assert cancel.status_code == 200
    assert terminal["status"] == "cancelled"
    assert snapshot.json() is None


def test_websocket_disconnect_does_not_cancel_active_job(tmp_path):
    service = ApiScanService()
    service.release.clear()
    api = scan_api(tmp_path, service)

    with TestClient(api) as client:
        client.put(
            "/options-screeners/settings/ticker-lists/csp_cc",
            json={"tickers": ["AAPL"]},
        )
        with client.websocket_connect("/options-screeners/scans/ws"):
            start = client.post("/options-screeners/scans/csp")
            job_id = start.json()["id"]
            assert service.started.wait(1)

        assert client.get(f"/options-screeners/jobs/{job_id}").json()["status"] == (
            "active"
        )
        service.release.set()
        terminal = wait_for_api_terminal(client, job_id)

    assert terminal["status"] == "completed"
    assert service.cancel_calls == 1  # App shutdown only.


def test_live_websocket_emits_progress_and_finished_events(tmp_path):
    service = ApiScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    api = scan_api(tmp_path, service)

    with TestClient(api) as client:
        client.put(
            "/options-screeners/settings/ticker-lists/csp_cc",
            json={"tickers": ["AAPL"]},
        )
        with client.websocket_connect("/options-screeners/scans/ws") as websocket:
            start = client.post("/options-screeners/scans/csp")
            events = [websocket.receive_json() for _ in range(3)]

    assert start.status_code == 200
    assert [event["type"] for event in events] == [
        "job_started",
        "job_updated",
        "job_finished",
    ]
    assert events[-1]["job"]["candidates"][0]["ticker"] == "AAPL"


def test_successful_zero_match_and_fatal_scan_snapshot_behavior_via_api(tmp_path):
    service = ApiScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    api = scan_api(tmp_path, service)

    with TestClient(api) as client:
        client.put(
            "/options-screeners/settings/ticker-lists/csp_cc",
            json={"tickers": ["AAPL"]},
        )
        first = wait_for_api_terminal(
            client,
            client.post("/options-screeners/scans/csp").json()["id"],
        )
        service.prepare_error = RuntimeError("fatal setup")
        failed = wait_for_api_terminal(
            client,
            client.post("/options-screeners/scans/csp").json()["id"],
        )
        after_failure = client.get("/options-screeners/snapshots/csp").json()
        service.results.clear()
        zero_match = wait_for_api_terminal(
            client,
            client.post("/options-screeners/scans/csp").json()["id"],
        )
        final_snapshot = client.get("/options-screeners/snapshots/csp").json()

    assert failed["status"] == "failed"
    assert after_failure["job_id"] == first["id"]
    assert zero_match["status"] == "completed"
    assert final_snapshot["job_id"] == zero_match["id"]
    assert final_snapshot["candidates"] == []


def test_quote_refresh_endpoint_uses_scan_service(tmp_path):
    api = scan_api(tmp_path, ApiScanService())
    payload = {
        "ticker": "AAPL",
        "expiration": "2026-07-17",
        "strike": 100,
        "right": "PUT",
        "contract": {"con_id": 123, "local_symbol": "AAPL PUT"},
    }

    with TestClient(api) as client:
        response = client.post("/options-screeners/quotes/refresh", json=payload)

    assert response.status_code == 200
    assert response.json()["midpoint"] == 1.1
    assert response.json()["refreshed_at"].endswith("+00:00")


def test_call_quote_refresh_endpoint_preserves_call_side(tmp_path):
    api = scan_api(tmp_path, ApiScanService())
    payload = {
        "ticker": "AAPL",
        "expiration": "2026-07-17",
        "strike": 110,
        "right": "CALL",
        "contract": {"con_id": 456, "local_symbol": "AAPL CALL"},
    }

    with TestClient(api) as client:
        response = client.post("/options-screeners/quotes/refresh", json=payload)

    assert response.status_code == 200
    assert response.json()["right"] == "CALL"
    assert response.json()["contract"]["con_id"] == 456


def test_spread_quote_refresh_endpoint_uses_scan_service(tmp_path):
    api = scan_api(tmp_path, ApiScanService())
    payload = {
        "strategy": "put_credit_spread",
        "ticker": "AAPL",
        "expiration": "2026-07-17",
        "short_strike": 100,
        "long_strike": 95,
        "short_contract": {"con_id": 123, "local_symbol": "AAPL SHORT PUT"},
        "long_contract": {"con_id": 124, "local_symbol": "AAPL LONG PUT"},
    }

    with TestClient(api) as client:
        response = client.post(
            "/options-screeners/quotes/refresh-spread",
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["net_midpoint"] == 1.25
    assert response.json()["maximum_loss"] == 3.75


def scan_api(tmp_path, service):
    return make_api(
        options_screeners_database_path=tmp_path / "options-screeners.sqlite3",
        options_screener_scan_service=service,
    )


def wait_for_api_terminal(client, job_id, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/options-screeners/jobs/{job_id}")
        job = response.json()
        if job["status"] != "active":
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not finish.")


def candidate(ticker):
    return CashSecuredPutCandidate(
        ticker=ticker,
        annualized_return=20,
        stock_price=110,
        strike=100,
        expiration="2026-07-17",
        dte=30,
        delta=-0.2,
        bid=1,
        ask=1.2,
        discount_percentage=9.09,
        contract=OptionContractIdentity(con_id=123, local_symbol=f"{ticker} PUT"),
    )
