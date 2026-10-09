import json

import pytest
from fastapi.testclient import TestClient

from app.day_trading_tracker.store import DayTradingTrackerValidationError
from tests.conftest import make_api


def create_day_trading_tracker_test_app(tmp_path):
    return make_api(
        day_trading_tracker_database_path=tmp_path / "day-trading-tracker.sqlite3",
    )


def test_month_fetch_returns_saved_rows_grouped_by_date(tmp_path):
    api = create_day_trading_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        first_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={
                "trades": [
                    {
                        "id": "row-2",
                        "display_order": 2,
                        "sell": 12.5,
                    },
                    {
                        "id": "row-1",
                        "display_order": 1,
                        "buy": 10.25,
                        "sell": 11.5,
                        "size": 2,
                        "fee": 1.5,
                    },
                ],
            },
        )
        client.put(
            "/day-trading-tracker/days/2026-08-19/trades",
            json={
                "trades": [
                    {
                        "id": "row-3",
                        "display_order": 1,
                        "buy": 20,
                        "sell": 19.5,
                        "size": 1,
                        "fee": 2,
                    },
                ],
            },
        )
        month_response = client.get("/day-trading-tracker/months/2026-08")

    assert first_response.status_code == 200
    assert [row["id"] for row in first_response.json()["trades"]] == [
        "row-1",
        "row-2",
    ]
    assert first_response.json()["trades"][0]["buy"] == 10.25
    assert first_response.json()["trades"][0]["fee"] == 1.5
    assert first_response.json()["trades"][1]["buy"] is None
    assert month_response.status_code == 200
    assert month_response.json()["month"] == "2026-08"
    assert [day["date"] for day in month_response.json()["days"]] == [
        "2026-08-19",
        "2026-08-20",
    ]
    assert month_response.json()["days"][1]["trades"][0]["id"] == "row-1"


def test_saving_empty_trades_clears_the_date(tmp_path):
    api = create_day_trading_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={"trades": [{"id": "row-1", "display_order": 1}]},
        )
        clear_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={"trades": []},
        )
        month_response = client.get("/day-trading-tracker/months/2026-08")

    assert clear_response.status_code == 200
    assert clear_response.json() == {"date": "2026-08-20", "trades": []}
    assert month_response.json() == {"month": "2026-08", "days": []}


def test_date_and_month_bounds_are_enforced(tmp_path):
    api = create_day_trading_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        before_month_response = client.get("/day-trading-tracker/months/2026-07")
        future_month_response = client.get("/day-trading-tracker/months/9999-12")
        bad_month_response = client.get("/day-trading-tracker/months/not-a-month")
        before_date_response = client.put(
            "/day-trading-tracker/days/2026-07-31/trades",
            json={"trades": []},
        )
        future_date_response = client.put(
            "/day-trading-tracker/days/9999-12-31/trades",
            json={"trades": []},
        )
        bad_date_response = client.put(
            "/day-trading-tracker/days/not-a-date/trades",
            json={"trades": []},
        )

    assert before_month_response.status_code == 422
    assert "before August 2026" in before_month_response.text
    assert future_month_response.status_code == 422
    assert "after the current month" in future_month_response.text
    assert bad_month_response.status_code == 422
    assert "month must use YYYY-MM" in bad_month_response.text
    assert before_date_response.status_code == 422
    assert "before August 1, 2026" in before_date_response.text
    assert future_date_response.status_code == 422
    assert "after the current date" in future_date_response.text
    assert bad_date_response.status_code == 422
    assert "trade_date must use YYYY-MM-DD" in bad_date_response.text


def test_trade_validation_allows_drafts_and_rejects_bad_rows(tmp_path):
    api = create_day_trading_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        draft_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "buy": 10.5,
                    },
                    {
                        "display_order": 2,
                        "sell": 12.25,
                    },
                    {
                        "display_order": 3,
                        "size": 3,
                        "fee": 0,
                    },
                ],
            },
        )
        bad_size_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={"trades": [{"display_order": 1, "size": 0}]},
        )
        decimal_size_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={"trades": [{"display_order": 1, "size": 1.5}]},
        )
        negative_fee_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={"trades": [{"display_order": 1, "fee": -1}]},
        )
        duplicate_order_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={
                "trades": [
                    {"id": "row-1", "display_order": 1},
                    {"id": "row-2", "display_order": 1},
                ],
            },
        )
        duplicate_id_response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            json={
                "trades": [
                    {"id": "row-1", "display_order": 1},
                    {"id": "row-1", "display_order": 2},
                ],
            },
        )

    assert draft_response.status_code == 200
    assert [row["buy"] for row in draft_response.json()["trades"]] == [
        10.5,
        None,
        None,
    ]
    assert bad_size_response.status_code == 422
    assert "positive whole number" in bad_size_response.text
    assert decimal_size_response.status_code == 422
    assert negative_fee_response.status_code == 422
    assert "fee must be zero or greater" in negative_fee_response.text
    assert duplicate_order_response.status_code == 422
    assert "Duplicate trade row display_order" in duplicate_order_response.text
    assert duplicate_id_response.status_code == 422
    assert "Duplicate trade row ids" in duplicate_id_response.text


def test_storage_validation_error_returns_422(tmp_path):
    api = create_day_trading_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        store = client.app.state.day_trading_tracker_store
        original_replace_day_rows = store.replace_day_rows

        def fail_replace(*_args, **_kwargs):
            raise DayTradingTrackerValidationError("Invalid day replacement.")

        store.replace_day_rows = fail_replace
        try:
            response = client.put(
                "/day-trading-tracker/days/2026-08-20/trades",
                json={"trades": []},
            )
        finally:
            store.replace_day_rows = original_replace_day_rows

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid day replacement."}


@pytest.mark.parametrize("field", ["buy", "sell", "fee"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_keep_exact_validation_detail(tmp_path, field, value):
    api = create_day_trading_tracker_test_app(tmp_path)
    row = {"display_order": 0}
    row[field] = value
    with TestClient(api) as client:
        response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades",
            content=json.dumps({"trades": [row]}),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "value_error",
                "loc": ["body", "trades", 0, field],
                "msg": "Value error, numeric values must be finite.",
                "input": str(value),
                "ctx": {"error": {}},
            },
        ],
    }


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [{"id": "same", "display_order": 0}, {"id": "same", "display_order": 1}],
            "Duplicate trade row ids are not allowed.",
        ),
        (
            [{"id": "a", "display_order": 0}, {"id": "b", "display_order": 0}],
            "Duplicate trade row display_order values are not allowed.",
        ),
        (
            [{"id": " same ", "display_order": 0}, {"id": "same", "display_order": 0}],
            "Duplicate trade row ids are not allowed.",
        ),
    ],
)
def test_row_ordering_keeps_exact_validation_detail(tmp_path, rows, message):
    api = create_day_trading_tracker_test_app(tmp_path)
    payload = {"trades": rows}
    with TestClient(api) as client:
        response = client.put(
            "/day-trading-tracker/days/2026-08-20/trades", json=payload,
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "value_error",
                "loc": ["body"],
                "msg": f"Value error, {message}",
                "input": payload,
                "ctx": {"error": {}},
            },
        ],
    }
