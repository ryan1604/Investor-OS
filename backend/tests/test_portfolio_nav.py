from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.portfolio.nav_store import DailyNav, DailyNavStore
from conftest import make_api


def nav(day="2026-09-01", **changes):
    return DailyNav.model_validate({
        "account": "DU1", "report_date": day, "nav": "123.123456789123456789",
        "currency": "USD", "source": "portfolioanalyst", **changes,
    })


def test_persistence_sorting_isolation_and_exact_amount(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = DailyNavStore(path)
    store.upsert_values([nav("2026-09-02"), nav(), nav(account="DU2")])
    reopened = DailyNavStore(path)
    result = reopened.history(" du1 ")
    assert [row.report_date for row in result.rows] == ["2026-09-01", "2026-09-02"]
    assert result.rows[0].nav == Decimal("123.123456789123456789")
    assert result.latest_report_date == "2026-09-02"
    assert reopened.list_accounts() == ["DU1", "DU2"]
    assert len(reopened.history("DU2").rows) == 1
    assert reopened.history("DU3").rows == []


def test_duplicates_corrections_and_source_precedence(tmp_path):
    store = DailyNavStore(tmp_path / "history.sqlite3")
    store.upsert_values([nav(), nav()])
    before = store.history("DU1").rows
    store.upsert_values([nav()])
    assert store.history("DU1").rows == before
    store.upsert_values([nav(nav="150", source="flex")])
    store.upsert_values([nav(nav="999")])
    assert store.history("DU1").rows[0].nav == Decimal("150")
    store.upsert_values([nav(nav="151", source="flex")])
    assert store.history("DU1").rows[0].nav == Decimal("151")
    assert store.history("DU1").rows[0].source == "flex"


def test_zero_and_negative_nav_are_valid_observations(tmp_path):
    store = DailyNavStore(tmp_path / "history.sqlite3")
    store.upsert_values([nav(nav="0"), nav("2026-09-02", nav="-25.50")])
    assert [r.nav for r in store.history("DU1").rows] == [Decimal("0"), Decimal("-25.50")]


def test_currency_conflict_rolls_back_whole_batch_and_changes_are_flagged(tmp_path):
    store = DailyNavStore(tmp_path / "history.sqlite3")
    store.upsert_values([nav()])
    with pytest.raises(ValueError, match="currency"):
        store.upsert_values([nav("2026-09-02"), nav(currency="SGD", source="flex")])
    assert len(store.history("DU1").rows) == 1
    store.upsert_values([nav("2026-09-03", currency="SGD")])
    result = store.history("DU1")
    assert result.currencies == ["SGD", "USD"]
    assert result.currency_changed
    assert [r.currency for r in result.rows] == ["USD", "SGD"]


@pytest.mark.parametrize("changes", [
    {"nav": "NaN"}, {"nav": "Infinity"}, {"nav": 1.1}, {"nav": True},
    {"report_date": "2026-02-30"}, {"report_date": "20260901"},
    {"currency": ""}, {"currency": "usd"}, {"account": " "}, {"source": "manual"},
])
def test_invalid_input(changes):
    with pytest.raises(ValidationError):
        nav(**changes)


def test_conflicting_duplicates_and_bypassed_validation_do_not_write(tmp_path):
    store = DailyNavStore(tmp_path / "history.sqlite3")
    with pytest.raises(ValueError, match="Conflicting"):
        store.upsert_values([nav(), nav(nav="5")])
    with pytest.raises(ValidationError):
        store.upsert_values([nav(), nav().model_copy(update={"report_date": "bad"})])
    assert store.list_accounts() == []


def test_sync_status_preserves_success_on_failure_and_sanitizes_errors(tmp_path):
    store = DailyNavStore(tmp_path / "history.sqlite3")
    store.record_sync("DU1")
    success = store.history("DU1").sync.last_successful_sync
    store.record_sync("DU1", error="credentials")
    reopened = DailyNavStore(store.database_path)
    status = reopened.history("DU1", configured=True).sync
    assert status.last_successful_sync == success
    assert status.error == "Check the IBKR Flex credentials."
    assert status.configured
    with pytest.raises(ValueError, match="Unknown"):
        store.record_sync("DU1", error="https://example.test/?token=secret")
    store.record_sync("DU1")
    assert store.history("DU1").sync.error is None
    assert store.history("DU2").sync.last_successful_sync is None


def test_offline_api_monthly_independence_and_restart(tmp_path):
    path = tmp_path / "history.sqlite3"
    api = make_api(portfolio_chart_values_database_path=path)
    with TestClient(api) as client:
        api.state.portfolio_nav_store.upsert_values([nav(), nav(account="DU2")])
        assert client.get("/portfolio").json()["status"]["connected"] is False
        response = client.get("/portfolio/nav?account=%20du1%20")
        assert response.status_code == 200
        data = response.json()
        assert data["rows"][0]["nav"] == "123.123456789123456789"
        assert data["account"] == "DU1"
        assert not data["currency_changed"]
        assert data["sync"] == {"configured": False, "last_successful_sync": None, "error": None, "state": "unconfigured"}
        assert client.get("/portfolio/nav/accounts").json() == ["DU1", "DU2"]
        for rows in ([{"month": "2026-09", "amount_invested": 200}], []):
            assert client.put("/portfolio/chart-values?account=DU1", json={"rows": rows}).status_code == 200
            api.state.portfolio_nav_store.upsert_values([nav()])
            monthly = client.get("/portfolio/chart-values?account=DU1").json()["rows"]
            assert [r["amount_invested"] for r in monthly] == ([200] if rows else [])
            assert client.get("/portfolio/nav?account=DU1").json() == data
        assert client.get("/portfolio/nav?account=DU3").json()["rows"] == []
        assert client.get("/portfolio/nav?account=%20").status_code == 400
        assert client.get("/portfolio/nav").status_code == 422
    with TestClient(make_api(portfolio_chart_values_database_path=path)) as client:
        assert client.get("/portfolio/nav?account=DU1").json() == data
