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

    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
        normalized_ticker = ticker.upper()
        price = (
            self.price.get(normalized_ticker)
            if isinstance(self.price, dict)
            else self.price
        )
        if price is None:
            raise OptionsDataUnavailable(f"No daily price data is available for {ticker}.")

        return OptionsAnalysisResponse(
            ticker=normalized_ticker,
            underlying_price=price,
            candles=[],
            bollinger_bands=[],
            rsi=[],
        )

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
        "current_price": 332.25,
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
    assert put_response.json()["current_price"] == 332.25
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
    api = create_stock_analysis_test_app(tmp_path)

    with TestClient(api) as client:
        client.put(
            "/stock-analysis/msft",
            json={
                "current_price": 332.25,
                "payload": {"bull": {}, "base": {}, "bear": {}},
            },
        )
        client.put(
            "/stock-analysis/aapl",
            json={
                "current_price": 195.5,
                "payload": {
                    "bull": {"revenue": [100]},
                    "base": {},
                    "bear": {},
                },
            },
        )
        response = client.get("/stock-analysis")

    assert response.status_code == 200
    assert [model["ticker"] for model in response.json()] == ["AAPL", "MSFT"]
    assert response.json()[0]["current_price"] == 195.5
    assert response.json()[1]["current_price"] == 332.25


def test_get_stock_analysis_current_price_returns_ib_backed_price(tmp_path):
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(price=42.5),
    )

    with TestClient(api) as client:
        response = client.get("/stock-analysis/hims/current-price")

    assert response.status_code == 200
    assert response.json() == {"ticker": "HIMS", "current_price": 42.5}


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
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(
            price={"AAPL": 205.0, "MSFT": None, "NFLX": None},
        ),
    )

    with TestClient(api) as client:
        client.put(
            "/stock-analysis/aapl",
            json={
                "current_price": 195.5,
                "payload": {"bull": {}, "base": {}, "bear": {}},
            },
        )
        client.put(
            "/stock-analysis/msft",
            json={
                "current_price": 332.25,
                "payload": {"bull": {}, "base": {}, "bear": {}},
            },
        )
        client.put(
            "/stock-analysis/nflx",
            json={"payload": {"bull": {}, "base": {}, "bear": {}}},
        )
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
