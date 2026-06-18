import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.sqlite import connect_row_database
from app.tickers import normalize_ticker


@dataclass(frozen=True)
class CompletedDailyBar:
    ticker: str
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


@dataclass(frozen=True)
class StoredDailyBar(CompletedDailyBar):
    fetched_at: str = ""


class OptionsDailyBarStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS options_daily_bars (
                    ticker TEXT NOT NULL,
                    trading_date TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (ticker, trading_date)
                )
                """
            )

    def upsert_completed_bars(
        self,
        bars: Iterable[CompletedDailyBar],
        *,
        current_date: date | None = None,
        fetched_at: datetime | None = None,
    ) -> None:
        finalized_before = current_date or date.today()
        fetched_at_value = (fetched_at or datetime.now(UTC)).isoformat()
        rows = [
            (
                normalize_ticker(bar.ticker),
                bar.trading_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                fetched_at_value,
            )
            for bar in bars
            if date.fromisoformat(bar.trading_date) < finalized_before
        ]

        if not rows:
            return

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO options_daily_bars (
                    ticker,
                    trading_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, trading_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )

    def get_completed_bars(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[StoredDailyBar]:
        query = """
            SELECT
                ticker,
                trading_date,
                open,
                high,
                low,
                close,
                volume,
                fetched_at
            FROM options_daily_bars
            WHERE ticker = ?
        """
        params: list[str] = [normalize_ticker(ticker)]

        if start_date is not None:
            query += " AND trading_date >= ?"
            params.append(start_date)

        if end_date is not None:
            query += " AND trading_date <= ?"
            params.append(end_date)

        query += " ORDER BY trading_date ASC"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [
            StoredDailyBar(
                ticker=row["ticker"],
                trading_date=row["trading_date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                fetched_at=row["fetched_at"],
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        return connect_row_database(self.database_path)
