import json
import sqlite3
from datetime import UTC, datetime

from app.stock_analysis.store import StockAnalysisStore


def make_store(tmp_path):
    return StockAnalysisStore(tmp_path / "stock-analysis.sqlite3")


def test_get_model_returns_none_for_unknown_ticker(tmp_path):
    store = make_store(tmp_path)

    assert store.get_model("AAPL") is None


def test_upsert_model_inserts_and_reads_normalized_ticker(tmp_path):
    store = make_store(tmp_path)

    store.upsert_model(
        " aapl ",
        version=1,
        payload={"bull": {"revenue": [100]}, "base": {}, "bear": {}},
        updated_at=datetime(2026, 6, 4, 1, 2, 3, tzinfo=UTC),
    )

    model = store.get_model("AAPL")

    assert model is not None
    assert model.ticker == "AAPL"
    assert model.version == 1
    assert model.current_price is None
    assert model.payload == {"bull": {"revenue": [100]}, "base": {}, "bear": {}}
    assert model.updated_at == "2026-06-04T01:02:03+00:00"


def test_upsert_model_updates_existing_payload(tmp_path):
    store = make_store(tmp_path)

    store.upsert_model(
        "MSFT",
        version=1,
        payload={"bull": {}, "base": {"revenue": [100]}, "bear": {}},
        updated_at=datetime(2026, 6, 4, 1, 0, tzinfo=UTC),
    )
    store.upsert_model(
        "msft",
        version=2,
        payload={"bull": {}, "base": {"revenue": [120]}, "bear": {"notes": None}},
        updated_at=datetime(2026, 6, 4, 2, 0, tzinfo=UTC),
    )

    model = store.get_model("MSFT")

    assert model is not None
    assert model.version == 2
    assert model.current_price is None
    assert model.payload["base"]["revenue"] == [120]
    assert model.payload["bear"]["notes"] is None
    assert model.updated_at == "2026-06-04T02:00:00+00:00"


def test_upsert_model_saves_nullable_current_price(tmp_path):
    store = make_store(tmp_path)

    store.upsert_model(
        "MSFT",
        version=1,
        current_price=123.45,
        payload={"bull": {}, "base": {}, "bear": {}},
        updated_at=datetime(2026, 6, 4, 1, 0, tzinfo=UTC),
    )
    store.upsert_model(
        "MSFT",
        version=1,
        current_price=None,
        payload={"bull": {}, "base": {"revenue": [100]}, "bear": {}},
        updated_at=datetime(2026, 6, 4, 2, 0, tzinfo=UTC),
    )

    model = store.get_model("MSFT")

    assert model is not None
    assert model.current_price is None
    assert model.payload["base"]["revenue"] == [100]


def test_list_models_returns_saved_models_ordered_by_ticker(tmp_path):
    store = make_store(tmp_path)
    store.upsert_model(
        "MSFT",
        version=1,
        payload={"bull": {}, "base": {"revenue": [100]}, "bear": {}},
        updated_at=datetime(2026, 6, 4, 2, 0, tzinfo=UTC),
    )
    store.upsert_model(
        "AAPL",
        version=2,
        current_price=195.5,
        payload={"bull": {"revenue": [200]}, "base": {}, "bear": {}},
        updated_at=datetime(2026, 6, 4, 1, 0, tzinfo=UTC),
    )

    models = store.list_models()

    assert [model.ticker for model in models] == ["AAPL", "MSFT"]
    assert models[0].current_price == 195.5
    assert models[1].payload["base"]["revenue"] == [100]


def test_update_current_price_preserves_existing_model_payload(tmp_path):
    store = make_store(tmp_path)
    store.upsert_model(
        "HIMS",
        version=3,
        payload={"bull": {"revenue": [100]}, "base": {}, "bear": {}},
        updated_at=datetime(2026, 6, 4, 1, 0, tzinfo=UTC),
    )

    model = store.update_current_price(
        "hims",
        42.5,
        updated_at=datetime(2026, 6, 4, 2, 0, tzinfo=UTC),
    )

    assert model.ticker == "HIMS"
    assert model.version == 3
    assert model.current_price == 42.5
    assert model.payload == {"bull": {"revenue": [100]}, "base": {}, "bear": {}}
    assert model.updated_at == "2026-06-04T02:00:00+00:00"


def test_update_current_price_inserts_empty_model_for_new_ticker(tmp_path):
    store = make_store(tmp_path)

    model = store.update_current_price(
        "HIMS",
        42.5,
        updated_at=datetime(2026, 6, 4, 2, 0, tzinfo=UTC),
    )

    assert model.ticker == "HIMS"
    assert model.version == 1
    assert model.current_price == 42.5
    assert model.payload == {"bull": {}, "base": {}, "bear": {}}


def test_store_reads_legacy_rows_without_current_price_column(tmp_path):
    database_path = tmp_path / "stock-analysis.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE stock_analysis_models (
                ticker TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO stock_analysis_models (
                ticker,
                version,
                payload_json,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "AAPL",
                1,
                json.dumps({"bull": {}, "base": {}, "bear": {}}),
                "2026-06-04T01:02:03+00:00",
            ),
        )

    store = StockAnalysisStore(database_path)
    model = store.get_model("AAPL")

    assert model is not None
    assert model.current_price is None
