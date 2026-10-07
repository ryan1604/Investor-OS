import json

import pytest
from fastapi.testclient import TestClient

from app.portfolio_analysis.limits_store import RiskLimitsStore
from tests.conftest import make_api

SUGGESTED = {
    "beta_weighted_delta_multiple": 1.0,
    "margin_utilisation_percent": 30,
    "assignment_exposure_percent": 50,
    "largest_underlying_percent": 15,
    "realistic_path_loss_percent": 25,
    "margin_call_distance_percent": 25,
}


def saved_values(body):
    return {limit["key"]: limit["value"] for limit in body["limits"]}


def test_store_keeps_limits_per_account_and_replaces_them(tmp_path):
    path = tmp_path / "analysis.sqlite3"
    store = RiskLimitsStore(path)
    store.replace_limits("U1", {"margin_utilisation_percent": 30, "largest_underlying_percent": 15})
    store.replace_limits("U2", {"margin_utilisation_percent": 40})

    reopened = RiskLimitsStore(path)
    assert {limit.key: limit.value for limit in reopened.list_limits("U1")} == {
        "largest_underlying_percent": 15,
        "margin_utilisation_percent": 30,
    }
    assert [limit.value for limit in reopened.list_limits("U2")] == [40]
    assert reopened.list_limits("U3") == []

    reopened.replace_limits("U1", {"largest_underlying_percent": 20})
    assert [(limit.key, limit.value) for limit in reopened.list_limits("U1")] == [
        ("largest_underlying_percent", 20),
    ]
    assert [limit.value for limit in reopened.list_limits("U2")] == [40]


def test_limits_api_starts_empty_and_persists_per_account(tmp_path):
    path = tmp_path / "analysis.sqlite3"
    with TestClient(make_api(portfolio_analysis_database_path=path)) as client:
        empty = client.get("/portfolio/analysis/limits/U1")
        saved = client.put("/portfolio/analysis/limits/U1", json={"limits": SUGGESTED})
        other = client.get("/portfolio/analysis/limits/U2")

    assert empty.status_code == 200
    assert empty.json() == {"account": "U1", "limits": []}
    assert saved.status_code == 200
    assert saved_values(saved.json()) == SUGGESTED
    assert other.json()["limits"] == []

    with TestClient(make_api(portfolio_analysis_database_path=path)) as client:
        reloaded = client.get("/portfolio/analysis/limits/U1")
        cleared = client.put("/portfolio/analysis/limits/U1", json={"limits": {}})

    assert saved_values(reloaded.json()) == SUGGESTED
    assert all(limit["updated_at"] for limit in reloaded.json()["limits"])
    assert cleared.json()["limits"] == []


@pytest.mark.parametrize(
    "limits",
    [
        {"margin_utilisation_percent": -1},
        {"margin_utilisation_percent": float("inf")},
        {"margin_utilisation_percent": float("nan")},
        {"unknown_limit": 1},
    ],
)
def test_limits_api_rejects_invalid_values(tmp_path, limits):
    with TestClient(make_api(portfolio_analysis_database_path=tmp_path / "db.sqlite3")) as client:
        response = client.put(
            "/portfolio/analysis/limits/U1",
            content=json.dumps({"limits": limits}),
            headers={"Content-Type": "application/json"},
        )
        after = client.get("/portfolio/analysis/limits/U1")

    assert response.status_code == 422
    assert after.json()["limits"] == []


def test_limits_api_rejects_extra_fields_and_blank_accounts(tmp_path):
    with TestClient(make_api(portfolio_analysis_database_path=tmp_path / "db.sqlite3")) as client:
        extra = client.put(
            "/portfolio/analysis/limits/U1",
            json={"limits": {}, "enforce": True},
        )
        blank = client.put("/portfolio/analysis/limits/%20", json={"limits": SUGGESTED})

    assert extra.status_code == 422
    assert blank.status_code == 400
