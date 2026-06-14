from fastapi.testclient import TestClient

from app.options_trade_tracker.store import OptionsTradeTrackerValidationError
from conftest import make_api


def create_options_trade_tracker_test_app(tmp_path):
    return make_api(
        options_trade_tracker_database_path=(
            tmp_path / "options-trade-trackers.sqlite3"
        ),
    )


def create_tracker(client: TestClient, name: str = "Income"):
    response = client.post("/options-trade-trackers", json={"name": name})
    assert response.status_code == 200
    return response.json()["tracker"]


def test_list_trackers_returns_empty_list_before_creation(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.get("/options-trade-trackers")

    assert response.status_code == 200
    assert response.json() == {"trackers": []}


def test_tracker_crud_and_duplicate_name_validation(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        tracker = create_tracker(client, "Income")
        duplicate_response = client.post(
            "/options-trade-trackers",
            json={"name": "income"},
        )
        rename_response = client.patch(
            f"/options-trade-trackers/{tracker['id']}",
            json={"name": "Growth"},
        )
        list_response = client.get("/options-trade-trackers")
        delete_response = client.delete(f"/options-trade-trackers/{tracker['id']}")
        get_deleted_response = client.get(f"/options-trade-trackers/{tracker['id']}")

    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {"detail": "Tracker name already exists."}
    assert rename_response.status_code == 200
    assert rename_response.json()["tracker"]["name"] == "Growth"
    assert [row["name"] for row in list_response.json()["trackers"]] == ["Growth"]
    assert delete_response.status_code == 204
    assert get_deleted_response.status_code == 404


def test_blank_tracker_names_are_rejected(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        response = client.post("/options-trade-trackers", json={"name": " "})

    assert response.status_code == 422
    assert "Tracker name is required" in response.text


def test_trades_and_notes_save_and_reload_for_selected_tracker(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        first_tracker = create_tracker(client, "Income")
        second_tracker = create_tracker(client, "Growth")

        first_trades_response = client.put(
            f"/options-trade-trackers/{first_tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "id": "row-2",
                        "display_order": 2,
                        "status": "In Progress",
                        "ticker": " msft ",
                    },
                    {
                        "id": "row-1",
                        "display_order": 1,
                        "status": "Completed",
                        "strategy": "Wheel",
                        "ticker": "aapl",
                        "month": "jan",
                        "size": 1,
                        "strike_price": 190,
                        "credit_debit": 1.2,
                    },
                ],
            },
        )
        client.put(
            f"/options-trade-trackers/{second_tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "id": "row-3",
                        "display_order": 1,
                        "status": "Completed",
                        "strategy": "Spread",
                        "ticker": "NVDA",
                        "month": "feb",
                        "size": 2,
                        "strike_price": 150,
                        "credit_debit": 0.5,
                        "exit": 0.1,
                    },
                ],
            },
        )
        client.put(
            f"/options-trade-trackers/{first_tracker['id']}/notes",
            json={"notes": "First notes"},
        )
        client.put(
            f"/options-trade-trackers/{second_tracker['id']}/notes",
            json={"notes": "Second notes"},
        )
        first_get_response = client.get(
            f"/options-trade-trackers/{first_tracker['id']}"
        )
        second_get_response = client.get(
            f"/options-trade-trackers/{second_tracker['id']}"
        )

    assert first_trades_response.status_code == 200
    assert [row["id"] for row in first_get_response.json()["trades"]] == [
        "row-1",
        "row-2",
    ]
    assert first_get_response.json()["trades"][0]["strategy"] == "WHEEL"
    assert first_get_response.json()["trades"][0]["ticker"] == "AAPL"
    assert first_get_response.json()["trades"][0]["exit"] is None
    assert first_get_response.json()["notes"] == "First notes"
    assert [row["ticker"] for row in second_get_response.json()["trades"]] == [
        "NVDA"
    ]
    assert second_get_response.json()["notes"] == "Second notes"
    assert first_get_response.json()["trades"][0]["size"] == 1
    assert second_get_response.json()["trades"][0]["credit_debit"] == 0.5


def test_two_trackers_accept_the_same_trade_row_id(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        first_tracker = create_tracker(client, "Income")
        second_tracker = create_tracker(client, "Growth")
        responses = [
            client.put(
                f"/options-trade-trackers/{tracker['id']}/trades",
                json={
                    "trades": [
                        {
                            "id": "shared-row",
                            "display_order": 1,
                            "status": "In Progress",
                        }
                    ]
                },
            )
            for tracker in (first_tracker, second_tracker)
        ]

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["trades"][0]["id"] == "shared-row"
    assert responses[1].json()["trades"][0]["id"] == "shared-row"


def test_strategy_options_are_global_and_survive_tracker_deletion(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        tracker = create_tracker(client, "Income")
        put_response = client.put(
            "/options-trade-trackers/strategy-options",
            json={"strategies": ["Wheel", "Iron Condor"]},
        )
        second_tracker = create_tracker(client, "Growth")
        second_get_response = client.get(
            f"/options-trade-trackers/{second_tracker['id']}"
        )
        delete_response = client.delete(f"/options-trade-trackers/{tracker['id']}")
        get_response = client.get("/options-trade-trackers/strategy-options")

    assert put_response.status_code == 200
    assert second_get_response.json()["strategy_options"] == ["WHEEL", "IRON CONDOR"]
    assert delete_response.status_code == 204
    assert get_response.json() == {"strategies": ["WHEEL", "IRON CONDOR"]}


def test_trade_validation_rejects_invalid_month_status_numbers_and_completed_rows(
    tmp_path,
):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        tracker = create_tracker(client, "Income")
        invalid_month_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "In Progress",
                        "month": "not-a-month",
                    }
                ]
            },
        )
        invalid_status_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={"trades": [{"display_order": 1, "status": "Open"}]},
        )
        invalid_number_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={"trades": [{"display_order": 1, "size": "abc"}]},
        )
        invalid_completed_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "Completed",
                        "strategy": "Wheel",
                    }
                ]
                },
            )
        zero_size_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "Completed",
                        "strategy": "Wheel",
                        "ticker": "AAPL",
                        "month": "jan",
                        "size": 0,
                        "strike_price": 190,
                        "credit_debit": 1.2,
                    }
                ]
            },
        )
        negative_size_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "Completed",
                        "strategy": "Wheel",
                        "ticker": "AAPL",
                        "month": "jan",
                        "size": -2,
                        "strike_price": 190,
                        "credit_debit": 1.2,
                        "exit": 0,
                    }
                ]
            },
        )
        negative_exit_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "Completed",
                        "strategy": "Wheel",
                        "ticker": "AAPL",
                        "month": "jan",
                        "size": -2,
                        "strike_price": 190,
                        "credit_debit": 1.2,
                        "exit": -0.1,
                    }
                ]
            },
        )
        invalid_in_progress_currency_responses = [
            client.put(
                f"/options-trade-trackers/{tracker['id']}/trades",
                json={
                    "trades": [
                        {
                            "display_order": 1,
                            "status": "In Progress",
                            field: value,
                        }
                    ]
                },
            )
            for field, value in (
                ("strike_price", -1),
                ("strike_price", 0),
                ("credit_debit", -1),
                ("credit_debit", 0),
                ("exit", -0.1),
            )
        ]
        partial_in_progress_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "In Progress",
                    }
                ]
            },
        )
        zero_credit_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "Completed",
                        "strategy": "Wheel",
                        "ticker": "AAPL",
                        "month": "jan",
                        "size": -2,
                        "strike_price": 190,
                        "credit_debit": 0,
                    }
                ]
            },
        )
        valid_month_key_response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {
                        "display_order": 1,
                        "status": "In Progress",
                        "month": "jan",
                    }
                ]
            },
        )

    assert invalid_month_response.status_code == 422
    assert "month must be jan-dec" in invalid_month_response.text
    assert invalid_status_response.status_code == 422
    assert invalid_number_response.status_code == 422
    assert invalid_completed_response.status_code == 422
    assert "Completed rows require" in invalid_completed_response.text
    assert zero_size_response.status_code == 422
    assert "non-zero size" in zero_size_response.text
    assert negative_size_response.status_code == 200
    assert negative_size_response.json()["trades"][0]["size"] == -2
    assert negative_exit_response.status_code == 422
    assert "exit must be greater than or equal to zero" in negative_exit_response.text
    assert zero_credit_response.status_code == 422
    assert "credit_debit must be greater than zero" in zero_credit_response.text
    assert [response.status_code for response in invalid_in_progress_currency_responses] == [
        422,
        422,
        422,
        422,
        422,
    ]
    assert partial_in_progress_response.status_code == 200
    assert valid_month_key_response.status_code == 200


def test_trade_validation_rejects_duplicate_row_order(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        tracker = create_tracker(client, "Income")
        response = client.put(
            f"/options-trade-trackers/{tracker['id']}/trades",
            json={
                "trades": [
                    {"id": "row-1", "display_order": 1},
                    {"id": "row-2", "display_order": 1},
                ]
            },
        )

    assert response.status_code == 422
    assert "Duplicate trade row display_order" in response.text


def test_storage_validation_error_returns_422(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        tracker = create_tracker(client, "Income")
        store = client.app.state.options_trade_tracker_store
        original_replace_trades = store.replace_trades

        def fail_replace(*_args, **_kwargs):
            raise OptionsTradeTrackerValidationError("Invalid trade replacement.")

        store.replace_trades = fail_replace
        try:
            response = client.put(
                f"/options-trade-trackers/{tracker['id']}/trades",
                json={"trades": []},
            )
        finally:
            store.replace_trades = original_replace_trades

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid trade replacement."}


def test_missing_tracker_mutations_return_not_found(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        trades_response = client.put(
            "/options-trade-trackers/missing/trades",
            json={"trades": []},
        )
        notes_response = client.put(
            "/options-trade-trackers/missing/notes",
            json={"notes": "Missing notes"},
        )
        rename_response = client.patch(
            "/options-trade-trackers/missing",
            json={"name": "Missing"},
        )
        delete_response = client.delete("/options-trade-trackers/missing")

    assert trades_response.status_code == 404
    assert notes_response.status_code == 404
    assert rename_response.status_code == 404
    assert delete_response.status_code == 404


def test_no_google_sheets_import_api_is_exposed(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)
    paths = api.openapi()["paths"]

    assert all("google" not in path.lower() for path in paths)
    assert all("sheet" not in path.lower() for path in paths)
    assert all("import" not in path.lower() for path in paths)


def test_strategy_options_normalize_casing_and_reject_case_duplicates(tmp_path):
    api = create_options_trade_tracker_test_app(tmp_path)

    with TestClient(api) as client:
        normalized_response = client.put(
            "/options-trade-trackers/strategy-options",
            json={"strategies": [" wheel ", "iron   condor"]},
        )
        duplicate_response = client.put(
            "/options-trade-trackers/strategy-options",
            json={"strategies": ["Wheel", "wheel"]},
        )

    assert normalized_response.status_code == 200
    assert normalized_response.json() == {"strategies": ["WHEEL", "IRON CONDOR"]}
    assert duplicate_response.status_code == 422
    assert "Duplicate strategy options" in duplicate_response.text
