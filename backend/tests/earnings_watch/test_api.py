import asyncio
from datetime import date

from fastapi.testclient import TestClient

from app.main import AppOverrides, create_app
from tests.conftest import (
    FakePortfolioClient,
    FakeUnavailableOptionsClient,
    make_test_settings,
)


def test_get_returns_saved_rows_immediately_and_no_store_cache_header(tmp_path):
    provider = BlockingProvider({"AAPL": date(2026, 7, 30)})
    api = make_earnings_api(tmp_path, provider)

    with TestClient(api) as client:
        client.post("/earnings-watch/tickers", json={"tickers": "AAPL"})
        response = client.get("/earnings-watch")
        provider.release()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["rows"][0]["ticker"] == "AAPL"
    assert response.json()["rows"][0]["earnings_date"] is None
    assert response.json()["refresh"]["state"] == "refreshing"
    assert provider.calls == 1


def test_mutation_endpoints_update_durable_watchlist(tmp_path):
    api = make_earnings_api(tmp_path, StaticProvider({"MSFT": date(2026, 8, 1)}))

    with TestClient(api) as client:
        added = client.post(
            "/earnings-watch/tickers",
            json={"tickers": "msft AAPL bad/ticker msft"},
        )
        reviewed = client.put(
            "/earnings-watch/tickers/msft/reviewed",
            json={"reviewed": True},
        )
        removed = client.delete("/earnings-watch/tickers/aapl")
        cleared = client.post("/earnings-watch/reviews/clear")

    assert added.status_code == 200
    assert added.json()["added"] == ["MSFT", "AAPL"]
    assert added.json()["existing"] == []
    assert added.json()["rejected"] == ["bad/ticker"]
    assert reviewed.json()["reviewed"] is True
    assert removed.json()["ticker"] == "AAPL"
    rows = cleared.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["ticker"] == "MSFT"
    assert rows[0]["reviewed"] is False


def make_earnings_api(tmp_path, provider):
    return create_app(
        make_test_settings(
            tmp_path,
            earnings_watch_database_path=tmp_path / "earnings-watch.sqlite3",
        ),
        AppOverrides(
            client=FakePortfolioClient(),
            options_client=FakeUnavailableOptionsClient(),
            earnings_calendar_provider=provider,
        ),
    )


class StaticProvider:
    def __init__(self, entries):
        self.entries = entries
        self.calls = 0
        self.closed = False

    async def fetch_calendar(self, *, today=None):
        self.calls += 1
        return self.entries

    async def aclose(self):
        self.closed = True


class BlockingProvider(StaticProvider):
    def __init__(self, entries):
        super().__init__(entries)
        self._release = False

    async def fetch_calendar(self, *, today=None):
        self.calls += 1
        while not self._release:
            await asyncio.sleep(0.01)
        return self.entries

    def release(self):
        self._release = True
