import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.sqlite import RowDatabase


class DayTradingTrackerValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DayTradingRow:
    id: str
    trade_date: str
    display_order: int
    buy: float | None
    sell: float | None
    size: int | None
    fee: float | None
    created_at: str
    updated_at: str


class DayTradingTrackerStore(RowDatabase):
    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS day_trading_rows (
                    trade_date TEXT NOT NULL,
                    id TEXT NOT NULL,
                    display_order INTEGER NOT NULL,
                    buy REAL,
                    sell REAL,
                    size INTEGER,
                    fee REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (trade_date, id),
                    UNIQUE (trade_date, display_order)
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(day_trading_rows)")
            }
            if "fee" not in columns:
                connection.execute("ALTER TABLE day_trading_rows ADD COLUMN fee REAL")
                connection.execute("UPDATE day_trading_rows SET fee = 2")

    def list_month_rows(self, month: str) -> list[DayTradingRow]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    trade_date,
                    id,
                    display_order,
                    buy,
                    sell,
                    size,
                    fee,
                    created_at,
                    updated_at
                FROM day_trading_rows
                WHERE trade_date >= ? AND trade_date < ?
                ORDER BY trade_date ASC, display_order ASC
                """,
                (f"{month}-01", next_month_key(month)),
            ).fetchall()

        return [day_trading_row_from_row(row) for row in rows]

    def replace_day_rows(
        self,
        trade_date: str,
        rows: list[DayTradingRow],
        *,
        now: datetime | None = None,
    ) -> list[DayTradingRow]:
        updated_at = (now or datetime.now(UTC)).isoformat()

        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM day_trading_rows WHERE trade_date = ?",
                    (trade_date,),
                )
                connection.executemany(
                    """
                    INSERT INTO day_trading_rows (
                        trade_date,
                        id,
                        display_order,
                        buy,
                        sell,
                        size,
                        fee,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            trade_date,
                            row.id or str(uuid.uuid4()),
                            row.display_order,
                            row.buy,
                            row.sell,
                            row.size,
                            row.fee,
                            updated_at,
                            updated_at,
                        )
                        for row in rows
                    ],
                )
        except sqlite3.IntegrityError as error:
            raise DayTradingTrackerValidationError(
                "Day trading rows violate date identity or display-order constraints."
            ) from error

        return [
            row
            for row in self.list_month_rows(trade_date[:7])
            if row.trade_date == trade_date
        ]


def day_trading_row_from_row(row: sqlite3.Row) -> DayTradingRow:
    return DayTradingRow(
        id=row["id"],
        trade_date=row["trade_date"],
        display_order=row["display_order"],
        buy=row["buy"],
        sell=row["sell"],
        size=row["size"],
        fee=row["fee"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def next_month_key(month: str) -> str:
    year = int(month[:4])
    month_number = int(month[5:])
    if month_number == 12:
        return f"{year + 1}-01-01"
    return f"{year}-{month_number + 1:02d}-01"
