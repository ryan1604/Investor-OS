import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.sqlite import connect_row_database


class OptionsTradeTrackerDuplicateNameError(ValueError):
    pass


class OptionsTradeTrackerNotFoundError(ValueError):
    pass


class OptionsTradeTrackerValidationError(ValueError):
    pass


@dataclass(frozen=True)
class OptionsTradeTracker:
    id: str
    name: str
    notes: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OptionsTrade:
    id: str
    tracker_id: str
    display_order: int
    status: str
    strategy: str | None
    ticker: str | None
    month: str | None
    size: float | None
    strike_price: float | None
    credit_debit: float | None
    exit: float | None
    created_at: str
    updated_at: str


class OptionsTradeTrackerStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS options_trade_trackers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._initialize_trade_rows(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS options_trade_strategy_options (
                    name TEXT PRIMARY KEY COLLATE NOCASE,
                    display_order INTEGER NOT NULL
                )
                """
            )

    def list_trackers(self) -> list[OptionsTradeTracker]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, notes, created_at, updated_at
                FROM options_trade_trackers
                ORDER BY name ASC
                """
            ).fetchall()

        return [tracker_from_row(row) for row in rows]

    def get_tracker(self, tracker_id: str) -> OptionsTradeTracker | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, notes, created_at, updated_at
                FROM options_trade_trackers
                WHERE id = ?
                """,
                (tracker_id,),
            ).fetchone()

        return tracker_from_row(row) if row is not None else None

    def create_tracker(
        self,
        name: str,
        *,
        tracker_id: str | None = None,
        now: datetime | None = None,
    ) -> OptionsTradeTracker:
        created_at = (now or datetime.now(UTC)).isoformat()
        new_tracker_id = tracker_id or str(uuid.uuid4())

        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO options_trade_trackers (
                        id,
                        name,
                        notes,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, '', ?, ?)
                    """,
                    (new_tracker_id, name.strip(), created_at, created_at),
                )
        except sqlite3.IntegrityError as error:
            raise OptionsTradeTrackerDuplicateNameError(
                "Tracker name already exists."
            ) from error

        tracker = self.get_tracker(new_tracker_id)
        if tracker is None:
            raise RuntimeError("Options trade tracker was not persisted.")
        return tracker

    def rename_tracker(
        self,
        tracker_id: str,
        name: str,
        *,
        now: datetime | None = None,
    ) -> OptionsTradeTracker:
        updated_at = (now or datetime.now(UTC)).isoformat()

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE options_trade_trackers
                    SET name = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name.strip(), updated_at, tracker_id),
                )
        except sqlite3.IntegrityError as error:
            raise OptionsTradeTrackerDuplicateNameError(
                "Tracker name already exists."
            ) from error

        if cursor.rowcount == 0:
            raise OptionsTradeTrackerNotFoundError("Tracker not found.")

        tracker = self.get_tracker(tracker_id)
        if tracker is None:
            raise OptionsTradeTrackerNotFoundError("Tracker not found.")
        return tracker

    def delete_tracker(self, tracker_id: str) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            cursor = connection.execute(
                "DELETE FROM options_trade_trackers WHERE id = ?",
                (tracker_id,),
            )

        if cursor.rowcount == 0:
            raise OptionsTradeTrackerNotFoundError("Tracker not found.")

    def list_trades(self, tracker_id: str) -> list[OptionsTrade]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    tracker_id,
                    display_order,
                    status,
                    strategy,
                    ticker,
                    month,
                    size,
                    strike_price,
                    credit_debit,
                    exit,
                    created_at,
                    updated_at
                FROM options_trade_rows
                WHERE tracker_id = ?
                ORDER BY display_order ASC
                """,
                (tracker_id,),
            ).fetchall()

        return [trade_from_row(row) for row in rows]

    def replace_trades(
        self,
        tracker_id: str,
        trades: list[OptionsTrade],
        *,
        now: datetime | None = None,
    ) -> list[OptionsTrade]:
        updated_at = (now or datetime.now(UTC)).isoformat()

        try:
            with self._connect() as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                if not self._tracker_exists(connection, tracker_id):
                    raise OptionsTradeTrackerNotFoundError("Tracker not found.")

                connection.execute(
                    "DELETE FROM options_trade_rows WHERE tracker_id = ?",
                    (tracker_id,),
                )
                connection.executemany(
                    """
                    INSERT INTO options_trade_rows (
                        id,
                        tracker_id,
                        display_order,
                        status,
                        strategy,
                        ticker,
                        month,
                        size,
                        strike_price,
                        credit_debit,
                        exit,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            trade.id or str(uuid.uuid4()),
                            tracker_id,
                            trade.display_order,
                            trade.status,
                            trade.strategy,
                            trade.ticker,
                            trade.month,
                            trade.size,
                            trade.strike_price,
                            trade.credit_debit,
                            trade.exit,
                            updated_at,
                            updated_at,
                        )
                        for trade in trades
                    ],
                )
                connection.execute(
                    """
                    UPDATE options_trade_trackers
                    SET updated_at = ?
                    WHERE id = ?
                    """,
                    (updated_at, tracker_id),
                )
        except sqlite3.IntegrityError as error:
            raise OptionsTradeTrackerValidationError(
                "Trade rows violate tracker identity or display-order constraints."
            ) from error

        return self.list_trades(tracker_id)

    def update_notes(
        self,
        tracker_id: str,
        notes: str,
        *,
        now: datetime | None = None,
    ) -> OptionsTradeTracker:
        updated_at = (now or datetime.now(UTC)).isoformat()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE options_trade_trackers
                SET notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (notes, updated_at, tracker_id),
            )

        if cursor.rowcount == 0:
            raise OptionsTradeTrackerNotFoundError("Tracker not found.")

        tracker = self.get_tracker(tracker_id)
        if tracker is None:
            raise OptionsTradeTrackerNotFoundError("Tracker not found.")
        return tracker

    def list_strategy_options(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT name
                FROM options_trade_strategy_options
                ORDER BY display_order ASC
                """
            ).fetchall()

        return [row["name"] for row in rows]

    def replace_strategy_options(self, strategies: list[str]) -> list[str]:
        with self._connect() as connection:
            connection.execute("DELETE FROM options_trade_strategy_options")
            connection.executemany(
                """
                INSERT INTO options_trade_strategy_options (name, display_order)
                VALUES (?, ?)
                """,
                [
                    (strategy, display_order)
                    for display_order, strategy in enumerate(strategies)
                ],
            )

        return self.list_strategy_options()

    def _connect(self) -> sqlite3.Connection:
        return connect_row_database(self.database_path)

    def _initialize_trade_rows(self, connection: sqlite3.Connection) -> None:
        existing_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'options_trade_rows'
            """
        ).fetchone()
        if existing_table is None:
            create_trade_rows_table(connection)
            return

        primary_key_columns = [
            row["name"]
            for row in sorted(
                connection.execute(
                    "PRAGMA table_info(options_trade_rows)"
                ).fetchall(),
                key=lambda row: row["pk"],
            )
            if row["pk"] > 0
        ]
        if primary_key_columns == ["tracker_id", "id"]:
            return

        connection.execute(
            "ALTER TABLE options_trade_rows RENAME TO options_trade_rows_legacy"
        )
        create_trade_rows_table(connection)
        connection.execute(
            """
            INSERT INTO options_trade_rows (
                tracker_id,
                id,
                display_order,
                status,
                strategy,
                ticker,
                month,
                size,
                strike_price,
                credit_debit,
                exit,
                created_at,
                updated_at
            )
            SELECT
                tracker_id,
                id,
                display_order,
                status,
                strategy,
                ticker,
                month,
                size,
                strike_price,
                credit_debit,
                exit,
                created_at,
                updated_at
            FROM options_trade_rows_legacy
            """
        )
        connection.execute("DROP TABLE options_trade_rows_legacy")

    def _tracker_exists(
        self,
        connection: sqlite3.Connection,
        tracker_id: str,
    ) -> bool:
        row = connection.execute(
            "SELECT 1 FROM options_trade_trackers WHERE id = ?",
            (tracker_id,),
        ).fetchone()
        return row is not None


def tracker_from_row(row: sqlite3.Row) -> OptionsTradeTracker:
    return OptionsTradeTracker(
        id=row["id"],
        name=row["name"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def trade_from_row(row: sqlite3.Row) -> OptionsTrade:
    return OptionsTrade(
        id=row["id"],
        tracker_id=row["tracker_id"],
        display_order=row["display_order"],
        status=row["status"],
        strategy=row["strategy"],
        ticker=row["ticker"],
        month=row["month"],
        size=row["size"],
        strike_price=row["strike_price"],
        credit_debit=row["credit_debit"],
        exit=row["exit"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_trade_rows_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE options_trade_rows (
            tracker_id TEXT NOT NULL,
            id TEXT NOT NULL,
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
            PRIMARY KEY (tracker_id, id),
            UNIQUE (tracker_id, display_order),
            FOREIGN KEY (tracker_id)
                REFERENCES options_trade_trackers(id)
                ON DELETE CASCADE
        )
        """
    )
