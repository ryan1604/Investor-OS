from fastapi.testclient import TestClient

from app.options.client import OptionsDataUnavailable
from app.schemas import OptionsAnalysisResponse
from conftest import make_api


class FakeOptionsAnalysisClient:
    def __init__(self, price: float | None = 42.5) -> None:
        self.price = price

    def get_analysis(self, ticker: str) -> OptionsAnalysisResponse:
        if self.price is None:
            raise OptionsDataUnavailable(f"No daily price data is available for {ticker}.")

        return OptionsAnalysisResponse(
            ticker=ticker.upper(),
            underlying_price=self.price,
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


def test_get_stock_analysis_current_price_returns_ib_backed_price(tmp_path):
    api = create_stock_analysis_test_app(
        tmp_path,
        options_client=FakeOptionsAnalysisClient(price=42.5),
    )

    with TestClient(api) as client:
        response = client.get("/stock-analysis/hims/current-price")

    assert response.status_code == 200
    assert response.json() == {"ticker": "HIMS", "current_price": 42.5}


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
