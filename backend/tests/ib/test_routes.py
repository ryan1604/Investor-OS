from fastapi.testclient import TestClient

from tests.conftest import FakePortfolioClient, make_api


def test_market_data_lines_reports_the_budget_without_changing_it():
    portfolio_client = FakePortfolioClient(connected=True)
    portfolio_client.market_data_lines.try_acquire("portfolio", 7)
    portfolio_client.market_data_lines.try_acquire("screener", 100, owner="scan")

    with TestClient(make_api(portfolio_client)) as client:
        response = client.get("/ib/market-data-lines")
        repeat = client.get("/ib/market-data-lines")

    assert response.status_code == 200
    body = response.json()
    assert body["capacity"] == 95
    assert body["used"] == 95
    assert body["used_by_group"]["portfolio"] == 7
    assert body["used_by_group"]["screener"] == 88
    assert body["pending_by_group"]["screener"] == 12
    assert repeat.json() == body
