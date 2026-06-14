import sqlite3
from datetime import UTC, datetime

import pytest

from app.options_trade_tracker.store import (
    OptionsTrade,
    OptionsTradeTrackerDuplicateNameError,
    OptionsTradeTrackerNotFoundError,
    OptionsTradeTrackerStore,
    OptionsTradeTrackerValidationError,
)


def make_store(tmp_path):
    return OptionsTradeTrackerStore(tmp_path / "options-trade-trackers.sqlite3")


def test_list_trackers_returns_empty_rows_before_creation(tmp_path):
    store = make_store(tmp_path)

    assert store.list_trackers() == []


def test_create_rename_and_list_trackers(tmp_path):
    store = make_store(tmp_path)
    created = store.create_tracker(
        "June Wheel",
        tracker_id="tracker-1",
        now=datetime(2026, 6, 6, 1, 2, 3, tzinfo=UTC),
    )

    renamed = store.rename_tracker(
        created.id,
        "July Wheel",
        now=datetime(2026, 6, 7, 1, 2, 3, tzinfo=UTC),
    )

    assert renamed.name == "July Wheel"
    assert renamed.created_at == "2026-06-06T01:02:03+00:00"
    assert renamed.updated_at == "2026-06-07T01:02:03+00:00"
    assert [tracker.name for tracker in store.list_trackers()] == ["July Wheel"]


def test_tracker_names_are_case_insensitive_unique(tmp_path):
    store = make_store(tmp_path)
    store.create_tracker("Income", tracker_id="tracker-1")

    with pytest.raises(OptionsTradeTrackerDuplicateNameError):
        store.create_tracker("income", tracker_id="tracker-2")


def test_replace_trades_and_notes_are_tracker_scoped(tmp_path):
    store = make_store(tmp_path)
    first_tracker = store.create_tracker("Income", tracker_id="tracker-1")
    second_tracker = store.create_tracker("Growth", tracker_id="tracker-2")

    store.replace_trades(
        first_tracker.id,
        [
            OptionsTrade(
                "row-2",
                first_tracker.id,
                2,
                "In Progress",
                None,
                "MSFT",
                None,
                None,
                None,
                None,
                None,
                "",
                "",
            ),
            OptionsTrade(
                "row-1",
                first_tracker.id,
                1,
                "Completed",
                "Wheel",
                "AAPL",
                "jan",
                1,
                190,
                1.2,
                None,
                "",
                "",
            ),
        ],
    )
    store.replace_trades(
        second_tracker.id,
        [
            OptionsTrade(
                "row-3",
                second_tracker.id,
                1,
                "Completed",
                "Spread",
                "NVDA",
                "feb",
                2,
                150,
                0.5,
                0.1,
                "",
                "",
            ),
        ],
    )
    store.update_notes(first_tracker.id, "First notes")
    store.update_notes(second_tracker.id, "Second notes")

    first_trades = store.list_trades(first_tracker.id)
    second_trades = store.list_trades(second_tracker.id)

    assert [trade.id for trade in first_trades] == ["row-1", "row-2"]
    assert first_trades[0].exit is None
    assert [trade.ticker for trade in second_trades] == ["NVDA"]
    assert second_trades[0].credit_debit == 0.5
    assert store.get_tracker(first_tracker.id).notes == "First notes"
    assert store.get_tracker(second_tracker.id).notes == "Second notes"


def test_trade_row_ids_are_scoped_to_each_tracker(tmp_path):
    store = make_store(tmp_path)
    first_tracker = store.create_tracker("Income", tracker_id="tracker-1")
    second_tracker = store.create_tracker("Growth", tracker_id="tracker-2")

    for tracker in (first_tracker, second_tracker):
        store.replace_trades(
            tracker.id,
            [
                OptionsTrade(
                    "shared-row",
                    tracker.id,
                    1,
                    "In Progress",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "",
                    "",
                )
            ],
        )

    assert [trade.id for trade in store.list_trades(first_tracker.id)] == [
        "shared-row"
    ]
    assert [trade.id for trade in store.list_trades(second_tracker.id)] == [
        "shared-row"
    ]


def test_replace_trades_rolls_back_integrity_failures(tmp_path):
    store = make_store(tmp_path)
    tracker = store.create_tracker("Income", tracker_id="tracker-1")
    store.replace_trades(
        tracker.id,
        [
            OptionsTrade(
                "existing-row",
                tracker.id,
                1,
                "In Progress",
                None,
                "AAPL",
                None,
                None,
                None,
                None,
                None,
                "",
                "",
            )
        ],
    )

    with pytest.raises(
        OptionsTradeTrackerValidationError,
        match="identity or display-order constraints",
    ):
        store.replace_trades(
            tracker.id,
            [
                OptionsTrade(
                    "row-1",
                    tracker.id,
                    1,
                    "In Progress",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "",
                    "",
                ),
                OptionsTrade(
                    "row-2",
                    tracker.id,
                    1,
                    "In Progress",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "",
                    "",
                ),
            ],
        )

    saved_trades = store.list_trades(tracker.id)
    assert [trade.id for trade in saved_trades] == ["existing-row"]
    assert saved_trades[0].ticker == "AAPL"


def test_store_migrates_legacy_global_trade_row_primary_key(tmp_path):
    database_path = tmp_path / "options-trade-trackers.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE options_trade_trackers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE options_trade_rows (
                id TEXT PRIMARY KEY,
                tracker_id TEXT NOT NULL,
                display_order INTEGER NOT NULL,
                status TEXT NOT NULL,
                strategy TEXT,
                ticker TEXT,
                month TEXT,
                size REAL,
                strike_price REAL,
                credit_debit REAL,
                exit REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (tracker_id, display_order)
            );
            INSERT INTO options_trade_trackers
                (id, name, notes, created_at, updated_at)
            VALUES
                ('tracker-1', 'Income', '', 'created', 'updated'),
                ('tracker-2', 'Growth', '', 'created', 'updated');
            INSERT INTO options_trade_rows
                (id, tracker_id, display_order, status, ticker, created_at, updated_at)
            VALUES
                ('legacy-row', 'tracker-1', 1, 'In Progress', 'AAPL', 'created', 'updated');
            """
        )

    store = OptionsTradeTrackerStore(database_path)
    store.replace_trades(
        "tracker-2",
        [
            OptionsTrade(
                "legacy-row",
                "tracker-2",
                1,
                "In Progress",
                None,
                "MSFT",
                None,
                None,
                None,
                None,
                None,
                "",
                "",
            )
        ],
    )

    assert store.list_trades("tracker-1")[0].ticker == "AAPL"
    assert store.list_trades("tracker-2")[0].ticker == "MSFT"
    with sqlite3.connect(database_path) as connection:
        primary_key_columns = [
            row[1]
            for row in sorted(
                connection.execute(
                    "PRAGMA table_info(options_trade_rows)"
                ).fetchall(),
                key=lambda row: row[5],
            )
            if row[5] > 0
        ]
    assert primary_key_columns == ["tracker_id", "id"]


def test_strategy_options_are_global_and_survive_tracker_deletion(tmp_path):
    store = make_store(tmp_path)
    tracker = store.create_tracker("Income", tracker_id="tracker-1")
    store.replace_strategy_options(["Wheel", "Iron Condor"])
    store.replace_trades(
        tracker.id,
        [
            OptionsTrade(
                "row-1",
                tracker.id,
                1,
                "In Progress",
                "Wheel",
                None,
                None,
                None,
                None,
                None,
                None,
                "",
                "",
            )
        ],
    )

    store.delete_tracker(tracker.id)

    assert store.list_strategy_options() == ["Wheel", "Iron Condor"]
    assert store.list_trades(tracker.id) == []
    assert store.get_tracker(tracker.id) is None


def test_replace_trades_accepts_signed_size_and_preserves_blank_exit(tmp_path):
    store = make_store(tmp_path)
    tracker = store.create_tracker("Income", tracker_id="tracker-1")

    saved_trades = store.replace_trades(
        tracker.id,
        [
            OptionsTrade(
                "row-1",
                tracker.id,
                1,
                "Completed",
                "Wheel",
                "AAPL",
                "jan",
                -2,
                190,
                1.5,
                None,
                "",
                "",
            )
        ],
    )

    assert saved_trades[0].size == -2
    assert saved_trades[0].exit is None
    assert store.list_trades(tracker.id)[0].size == -2


def test_delete_unknown_tracker_raises_not_found(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(OptionsTradeTrackerNotFoundError):
        store.delete_tracker("missing")
