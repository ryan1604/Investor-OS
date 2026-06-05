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
    assert model.payload["base"]["revenue"] == [120]
    assert model.payload["bear"]["notes"] is None
    assert model.updated_at == "2026-06-04T02:00:00+00:00"
