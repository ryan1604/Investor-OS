from fastapi.testclient import TestClient

from conftest import make_api


def create_portfolio_chart_values_test_app(tmp_path):
    return make_api(
        portfolio_chart_values_database_path=(
            tmp_path / "portfolio-chart-values.sqlite3"
        ),
    )


def test_put_portfolio_chart_values_saves_and_gets_rows_by_account(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)
    payload = {
        "rows": [
            {
                "month": "2026-03",
                "portfolio_value": 1300.25,
                "amount_invested": None,
            },
            {
                "month": "2026-01",
                "portfolio_value": None,
                "amount_invested": 1000.0,
            },
        ],
    }

    with TestClient(api) as client:
        put_response = client.put(
            "/portfolio/chart-values?account=du1234567",
            json=payload,
        )
        get_response = client.get("/portfolio/chart-values?account=DU1234567")

    assert put_response.status_code == 200
    assert get_response.status_code == 200
    assert put_response.json()["account"] == "DU1234567"
    assert [row["month"] for row in put_response.json()["rows"]] == [
        "2026-01",
        "2026-03",
    ]
    assert put_response.json() == get_response.json()
    assert put_response.json()["rows"][0]["updated_at"] is not None


def test_put_portfolio_chart_values_replaces_only_selected_account(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)

    with TestClient(api) as client:
        client.put(
            "/portfolio/chart-values?account=DU1234567",
            json={"rows": [{"month": "2026-01", "portfolio_value": 1000.0}]},
        )
        client.put(
            "/portfolio/chart-values?account=DU7654321",
            json={"rows": [{"month": "2026-02", "portfolio_value": 2000.0}]},
        )
        client.put(
            "/portfolio/chart-values?account=DU1234567",
            json={"rows": [{"month": "2026-03", "amount_invested": 950.0}]},
        )
        first_account_response = client.get(
            "/portfolio/chart-values?account=DU1234567"
        )
        second_account_response = client.get(
            "/portfolio/chart-values?account=DU7654321"
        )

    assert [row["month"] for row in first_account_response.json()["rows"]] == [
        "2026-03"
    ]
    assert [row["month"] for row in second_account_response.json()["rows"]] == [
        "2026-02"
    ]


def test_put_portfolio_chart_values_rejects_duplicate_months(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.put(
            "/portfolio/chart-values?account=DU1234567",
            json={
                "rows": [
                    {"month": "2026-01", "portfolio_value": 1000.0},
                    {"month": "2026-01", "amount_invested": 900.0},
                ],
            },
        )

    assert response.status_code == 422
    assert "Duplicate month values are not allowed" in response.text


def test_put_portfolio_chart_values_rejects_invalid_month(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.put(
            "/portfolio/chart-values?account=DU1234567",
            json={"rows": [{"month": "2026-13", "portfolio_value": 1000.0}]},
        )

    assert response.status_code == 422
    assert "month must use YYYY-MM format" in response.text


def test_put_portfolio_chart_values_rejects_fully_blank_rows(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.put(
            "/portfolio/chart-values?account=DU1234567",
            json={"rows": [{"month": "2026-01"}]},
        )

    assert response.status_code == 422
    assert "portfolio_value or amount_invested is required" in response.text


def test_put_portfolio_chart_values_rejects_invalid_numbers(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.put(
            "/portfolio/chart-values?account=DU1234567",
            json={"rows": [{"month": "2026-01", "portfolio_value": "abc"}]},
        )

    assert response.status_code == 422


def test_portfolio_chart_values_requires_account(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)

    with TestClient(api) as client:
        get_response = client.get("/portfolio/chart-values?account= ")
        put_response = client.put(
            "/portfolio/chart-values?account= ",
            json={"rows": [{"month": "2026-01", "portfolio_value": 1000.0}]},
        )

    assert get_response.status_code == 400
    assert get_response.json() == {"detail": "Account is required."}
    assert put_response.status_code == 400
    assert put_response.json() == {"detail": "Account is required."}


def test_live_portfolio_response_remains_separate_from_chart_values(tmp_path):
    api = create_portfolio_chart_values_test_app(tmp_path)

    with TestClient(api) as client:
        client.put(
            "/portfolio/chart-values?account=DU1234567",
            json={"rows": [{"month": "2026-01", "portfolio_value": 1000.0}]},
        )
        response = client.get("/portfolio")

    assert response.status_code == 200
    assert "rows" not in response.json()
