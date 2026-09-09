from datetime import UTC, datetime

import pytest

from app.day_trading_tracker.store import (
    DayTradingRow,
    DayTradingTrackerStore,
    DayTradingTrackerValidationError,
)


def make_store(tmp_path):
    return DayTradingTrackerStore(tmp_path / "day-trading-tracker.sqlite3")


def test_list_month_rows_returns_empty_rows_before_save(tmp_path):
    store = make_store(tmp_path)

    assert store.list_month_rows("2026-08") == []


def test_replace_day_rows_and_list_month_rows(tmp_path):
    store = make_store(tmp_path)

    store.replace_day_rows(
        "2026-08-20",
        [
            DayTradingRow("row-2", "2026-08-20", 2, None, 13.5, None, None, "", ""),
            DayTradingRow("row-1", "2026-08-20", 1, 10.25, 12.5, 2, 1.5, "", ""),
        ],
        now=datetime(2026, 8, 20, 1, 2, 3, tzinfo=UTC),
    )
    store.replace_day_rows(
        "2026-08-19",
        [
            DayTradingRow("row-3", "2026-08-19", 1, 20, 19.5, 1, 2, "", ""),
        ],
        now=datetime(2026, 8, 20, 1, 2, 4, tzinfo=UTC),
    )

    rows = store.list_month_rows("2026-08")

    assert [(row.trade_date, row.id) for row in rows] == [
        ("2026-08-19", "row-3"),
        ("2026-08-20", "row-1"),
        ("2026-08-20", "row-2"),
    ]
    assert rows[1].buy == 10.25
    assert rows[1].sell == 12.5
    assert rows[1].size == 2
    assert rows[1].fee == 1.5
    assert rows[1].created_at == "2026-08-20T01:02:03+00:00"
    assert rows[2].buy is None
    assert rows[2].sell == 13.5
    assert rows[2].size is None
    assert rows[2].fee is None


def test_replace_day_rows_clears_existing_rows(tmp_path):
    store = make_store(tmp_path)
    store.replace_day_rows(
        "2026-08-20",
        [DayTradingRow("row-1", "2026-08-20", 1, 10, 11, 1, 2, "", "")],
    )

    saved_rows = store.replace_day_rows("2026-08-20", [])

    assert saved_rows == []
    assert store.list_month_rows("2026-08") == []


def test_replace_day_rows_rolls_back_integrity_failures(tmp_path):
    store = make_store(tmp_path)
    store.replace_day_rows(
        "2026-08-20",
        [DayTradingRow("existing-row", "2026-08-20", 1, 10, 11, 1, 2, "", "")],
    )

    with pytest.raises(
        DayTradingTrackerValidationError,
        match="identity or display-order constraints",
    ):
        store.replace_day_rows(
            "2026-08-20",
            [
                DayTradingRow("row-1", "2026-08-20", 1, 10, 11, 1, 2, "", ""),
                DayTradingRow("row-2", "2026-08-20", 1, 12, 13, 1, 2, "", ""),
            ],
        )

    saved_rows = store.list_month_rows("2026-08")
    assert [row.id for row in saved_rows] == ["existing-row"]
    assert saved_rows[0].buy == 10


def test_list_month_rows_excludes_other_months(tmp_path):
    store = make_store(tmp_path)
    store.replace_day_rows(
        "2026-08-31",
        [DayTradingRow("aug-row", "2026-08-31", 1, 10, 11, 1, 2, "", "")],
    )
    store.replace_day_rows(
        "2026-09-01",
        [DayTradingRow("sep-row", "2026-09-01", 1, 12, 13, 1, 2, "", "")],
    )

    assert [row.id for row in store.list_month_rows("2026-08")] == ["aug-row"]
