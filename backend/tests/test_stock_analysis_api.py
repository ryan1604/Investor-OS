from fastapi.testclient import TestClient

from app.options.client import OptionsDataUnavailable
from app.schemas import OptionsAnalysisResponse
from conftest import make_api


class FakeOptionsAnalysisClient:
    def __init__(
        self,
        price: float | None | dict[str, float | None] = 42.5,
    ) -> None:
        self.price = price
        self.analysis_requests: list[str] = []
        self.price_requests: list[str] = []

    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
        self.analysis_requests.append(ticker)
        raise AssertionError("Price refresh must not invoke full options analysis.")

    def get_underlying_price(self, ticker: str) -> float:
        normalized_ticker = ticker.upper()
        self.price_requests.append(normalized_ticker)
        price = (
            self.price.get(normalized_ticker)
            if isinstance(self.price, dict)
            else self.price
        )
        if price is None:
            raise OptionsDataUnavailable(f"No daily price data is available for {ticker}.")

        return price

    def get_expirations(self, ticker):
        raise NotImplementedError

    def get_chain(self, ticker, expiration):
        raise NotImplementedError

    def stream_chain(self, ticker, expiration, *, stop_event):
        raise NotImplementedError

    def stream_chart(self, ticker, *, stop_event):
        raise NotImplementedError


def test_get_stock_analysis_returns_empty_model_for_first_time_ticker(tmp_path):
    api = create_stock_analysis_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.get("/stock-analysis/aapl")

    assert response.status_code == 200
    assert response.json() == {
        "ticker": "AAPL",
        "version": 1,
        "current_price": None,
        "payload": {"bull": {}, "base": {}, "bear": {}},
        "updated_at": None,
    }


def test_put_stock_analysis_saves_partial_scenarios_by_ticker(tmp_path):
    api = create_stock_analysis_test_app(tmp_path)
    payload = {
        "version": 2,
        "payload": {
            "bull": {"revenue": [100, None, 130]},
            "base": {"revenue": [90]},
            "bear": {},
        },
    }

    with TestClient(api) as client:
        put_response = client.put("/stock-analysis/msft", json=payload)
        get_response = client.get("/stock-analysis/MSFT")

    assert put_response.status_code == 200
    assert put_response.json()["ticker"] == "MSFT"
    assert put_response.json()["version"] == 2
    assert put_response.json()["current_price"] is None
    assert put_response.json()["payload"] == payload["payload"]
    assert put_response.json()["updated_at"] is not None
    assert get_response.status_code == 200
    assert get_response.json() == put_response.json()


def test_put_stock_analysis_requires_all_three_scenarios(tmp_path):
    api = create_stock_analysis_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.put(
            "/stock-analysis/aapl",
            json={"payload": {"bull": {}, "base": {}}},
        )

    assert response.status_code == 422


def test_get_stock_analysis_models_returns_saved_models_ordered(tmp_path):
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(
            price={"AAPL": 195.5, "MSFT": 332.25},
        ),
    )

    with TestClient(api) as client:
        client.put(
            "/stock-analysis/msft",
            json={
                "payload": {"bull": {}, "base": {}, "bear": {}},
            },
        )
        client.put(
            "/stock-analysis/aapl",
            json={
                "payload": {
                    "bull": {"revenue": [100]},
                    "base": {},
                    "bear": {},
                },
            },
        )
        client.get("/stock-analysis/msft/current-price")
        client.get("/stock-analysis/aapl/current-price")
        response = client.get("/stock-analysis")

    assert response.status_code == 200
    assert [model["ticker"] for model in response.json()] == ["AAPL", "MSFT"]
    assert response.json()[0]["current_price"] == 195.5
    assert response.json()[1]["current_price"] == 332.25


def test_delete_stock_analysis_removes_saved_model_and_price_snapshot(tmp_path):
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(price=195.5),
    )

    with TestClient(api) as client:
        client.put(
            "/stock-analysis/aapl",
            json={
                "payload": {"bull": {"revenue": [100]}, "base": {}, "bear": {}},
            },
        )
        client.get("/stock-analysis/aapl/current-price")
        delete_response = client.delete("/stock-analysis/aapl")
        second_delete_response = client.delete("/stock-analysis/aapl")
        list_response = client.get("/stock-analysis")
        model_response = client.get("/stock-analysis/aapl")
        readd_response = client.put(
            "/stock-analysis/aapl",
            json={
                "payload": {"bull": {}, "base": {"revenue": [250]}, "bear": {}},
            },
        )

    assert delete_response.status_code == 204
    assert second_delete_response.status_code == 204
    assert list_response.json() == []
    assert model_response.json() == {
        "ticker": "AAPL",
        "version": 1,
        "current_price": None,
        "payload": {"bull": {}, "base": {}, "bear": {}},
        "updated_at": None,
    }
    assert readd_response.status_code == 200
    assert readd_response.json()["current_price"] is None
    assert readd_response.json()["payload"] == {
        "bull": {},
        "base": {"revenue": [250]},
        "bear": {},
    }


def test_get_stock_analysis_current_price_returns_ib_backed_price(tmp_path):
    options_client = FakeOptionsAnalysisClient(price=42.5)
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=options_client,
    )

    with TestClient(api) as client:
        response = client.get("/stock-analysis/hims/current-price")

    assert response.status_code == 200
    assert response.json() == {"ticker": "HIMS", "current_price": 42.5}
    assert options_client.price_requests == ["HIMS"]
    assert options_client.analysis_requests == []


def test_get_stock_analysis_current_price_persists_snapshot(tmp_path):
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(price=42.5),
    )

    with TestClient(api) as client:
        price_response = client.get("/stock-analysis/hims/current-price")
        model_response = client.get("/stock-analysis/hims")

    assert price_response.status_code == 200
    assert model_response.status_code == 200
    assert model_response.json()["current_price"] == 42.5
    assert model_response.json()["payload"] == {"bull": {}, "base": {}, "bear": {}}
    assert model_response.json()["updated_at"] is not None


def test_refresh_stock_analysis_current_prices_updates_successful_tickers(tmp_path):
    options_client = FakeOptionsAnalysisClient(
        price={"AAPL": 195.5, "MSFT": 332.25, "NFLX": None},
    )
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=options_client,
    )

    with TestClient(api) as client:
        client.put(
            "/stock-analysis/aapl",
            json={
                "payload": {"bull": {}, "base": {}, "bear": {}},
            },
        )
        client.put(
            "/stock-analysis/msft",
            json={
                "payload": {"bull": {}, "base": {}, "bear": {}},
            },
        )
        client.put(
            "/stock-analysis/nflx",
            json={"payload": {"bull": {}, "base": {}, "bear": {}}},
        )
        client.get("/stock-analysis/aapl/current-price")
        client.get("/stock-analysis/msft/current-price")
        options_client.price = {"AAPL": 205.0, "MSFT": None, "NFLX": None}
        refresh_response = client.post("/stock-analysis/current-prices/refresh")
        models_response = client.get("/stock-analysis")

    assert refresh_response.status_code == 200
    assert refresh_response.json() == {
        "results": [
            {
                "ticker": "AAPL",
                "status": "refreshed",
                "current_price": 205.0,
                "message": None,
            },
            {
                "ticker": "MSFT",
                "status": "stale",
                "current_price": 332.25,
                "message": "No daily price data is available for MSFT.",
            },
            {
                "ticker": "NFLX",
                "status": "missing",
                "current_price": None,
                "message": "No daily price data is available for NFLX.",
            },
        ],
    }
    models_by_ticker = {
        model["ticker"]: model
        for model in models_response.json()
    }
    assert models_by_ticker["AAPL"]["current_price"] == 205.0
    assert models_by_ticker["MSFT"]["current_price"] == 332.25
    assert models_by_ticker["NFLX"]["current_price"] is None
    assert options_client.price_requests[-3:] == ["AAPL", "MSFT", "NFLX"]
    assert options_client.analysis_requests == []


def test_put_stock_analysis_preserves_focused_price_snapshot(tmp_path):
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(price=42.5),
    )

    with TestClient(api) as client:
        client.get("/stock-analysis/hims/current-price")
        response = client.put(
            "/stock-analysis/hims",
            json={
                "payload": {
                    "bull": {"revenue": [100]},
                    "base": {},
                    "bear": {},
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["current_price"] == 42.5
    assert response.json()["payload"]["bull"]["revenue"] == [100]


def test_get_stock_analysis_current_price_reports_unavailable_price(tmp_path):
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(price=None),
    )

    with TestClient(api) as client:
        response = client.get("/stock-analysis/hims/current-price")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No daily price data is available for HIMS.",
    }


def create_stock_analysis_test_app(tmp_path, options_client=None):
    return make_api(
        options_client=options_client,
        stock_analysis_database_path=tmp_path / "stock-analysis.sqlite3",
    )
