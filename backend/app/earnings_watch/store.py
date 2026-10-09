import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.sqlite import RowDatabase
from app.tickers import require_ticker

RefreshErrorCategory = (
    str  # not_configured, rate_limited, network, timeout, invalid_response
)


@dataclass(frozen=True)
class EarningsWatchRow:
    ticker: str
    reviewed: bool
    earnings_date: str | None
    provider_refresh_date: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EarningsRefreshMetadata:
    last_attempt_at: str | None
    last_success_at: str | None
    last_success_date: str | None
    outcome: str | None
    error_category: RefreshErrorCategory | None
    next_eligible_retry_at: str | None


class EarningsWatchStore(RowDatabase):
    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS earnings_watchlist (
                    ticker TEXT PRIMARY KEY,
                    reviewed INTEGER NOT NULL DEFAULT 0,
                    earnings_date TEXT,
                    provider_refresh_date TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS earnings_calendar_cache (
                    ticker TEXT PRIMARY KEY,
                    earnings_date TEXT NOT NULL,
                    provider_refresh_date TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS earnings_refresh_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_attempt_at TEXT,
                    last_success_at TEXT,
                    last_success_date TEXT,
                    outcome TEXT,
                    error_category TEXT,
                    next_eligible_retry_at TEXT
                )
                """
            )

    def add_tickers(
        self,
        tickers: list[str],
        *,
        now: datetime | None = None,
    ) -> tuple[list[EarningsWatchRow], list[str]]:
        normalized_tickers = [require_ticker(ticker) for ticker in tickers]
        base_time = now or datetime.now(UTC)
        added: list[str] = []
        existing: list[str] = []
        with self._connect() as connection:
            for ticker in normalized_tickers:
                existing_row = connection.execute(
                    "SELECT ticker FROM earnings_watchlist WHERE ticker = ?",
                    (ticker,),
                ).fetchone()
                if existing_row:
                    existing.append(ticker)
                    continue

                cache_row = connection.execute(
                    """
                    SELECT earnings_date, provider_refresh_date
                    FROM earnings_calendar_cache
                    WHERE ticker = ?
                    """,
                    (ticker,),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO earnings_watchlist (
                        ticker,
                        reviewed,
                        earnings_date,
                        provider_refresh_date,
                        created_at,
                        updated_at
                    )
                    VALUES (?, 0, ?, ?, ?, ?)
                """,
                    (
                        ticker,
                        cache_row["earnings_date"] if cache_row else None,
                        cache_row["provider_refresh_date"] if cache_row else None,
                        utc_timestamp(base_time + timedelta(microseconds=len(added))),
                        utc_timestamp(base_time + timedelta(microseconds=len(added))),
                    ),
                )
                added.append(ticker)
        return self.list_watchlist(), existing

    def get_ticker(self, ticker: str) -> EarningsWatchRow | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ticker, reviewed, earnings_date, provider_refresh_date,
                       created_at, updated_at
                FROM earnings_watchlist
                WHERE ticker = ?
                """,
                (require_ticker(ticker),),
            ).fetchone()
        return earnings_watch_row_from_row(row) if row else None

    def list_watchlist(self) -> list[EarningsWatchRow]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker, reviewed, earnings_date, provider_refresh_date,
                       created_at, updated_at
                FROM earnings_watchlist
                ORDER BY created_at ASC, ticker ASC
                """
            ).fetchall()
        return [earnings_watch_row_from_row(row) for row in rows]

    def set_reviewed(
        self,
        ticker: str,
        reviewed: bool,
        *,
        now: datetime | None = None,
    ) -> EarningsWatchRow:
        normalized_ticker = require_ticker(ticker)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE earnings_watchlist
                SET reviewed = ?, updated_at = ?
                WHERE ticker = ?
                """,
                (int(reviewed), utc_timestamp(now), normalized_ticker),
            )
        row = self.get_ticker(normalized_ticker)
        if row is None:
            raise KeyError(normalized_ticker)
        return row

    def clear_reviewed(self, *, now: datetime | None = None) -> list[EarningsWatchRow]:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE earnings_watchlist
                SET reviewed = 0, updated_at = ?
                WHERE reviewed != 0
                """,
                (utc_timestamp(now),),
            )
        return self.list_watchlist()

    def remove_ticker(self, ticker: str) -> EarningsWatchRow:
        normalized_ticker = require_ticker(ticker)
        row = self.get_ticker(normalized_ticker)
        if row is None:
            raise KeyError(normalized_ticker)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM earnings_watchlist WHERE ticker = ?",
                (normalized_ticker,),
            )
        return row

    def replace_calendar_cache(
        self,
        entries: dict[str, date],
        *,
        provider_refresh_date: date,
        fetched_at: datetime | None = None,
    ) -> None:
        timestamp = utc_timestamp(fetched_at)
        normalized_entries = {
            require_ticker(ticker): earnings_date.isoformat()
            for ticker, earnings_date in entries.items()
        }
        provider_refresh_date_value = provider_refresh_date.isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM earnings_calendar_cache")
            connection.executemany(
                """
                INSERT INTO earnings_calendar_cache (
                    ticker,
                    earnings_date,
                    provider_refresh_date,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        ticker,
                        earnings_date,
                        provider_refresh_date_value,
                        timestamp,
                    )
                    for ticker, earnings_date in normalized_entries.items()
                ],
            )
            connection.executemany(
                """
                UPDATE earnings_watchlist
                SET earnings_date = ?,
                    provider_refresh_date = ?,
                    updated_at = ?
                WHERE ticker = ?
                """,
                [
                    (
                        earnings_date,
                        provider_refresh_date_value,
                        timestamp,
                        ticker,
                    )
                    for ticker, earnings_date in normalized_entries.items()
                ],
            )

    def snapshot(self) -> tuple[list[EarningsWatchRow], EarningsRefreshMetadata]:
        with self._connect() as connection:
            row_values = connection.execute(
                """
                SELECT ticker, reviewed, earnings_date, provider_refresh_date,
                       created_at, updated_at
                FROM earnings_watchlist
                ORDER BY created_at ASC, ticker ASC
                """
            ).fetchall()
            metadata_row = connection.execute(
                """
                SELECT last_attempt_at, last_success_at, last_success_date,
                       outcome, error_category, next_eligible_retry_at
                FROM earnings_refresh_metadata
                WHERE id = 1
                """
            ).fetchone()
        rows = [earnings_watch_row_from_row(row) for row in row_values]
        metadata = (
            EarningsRefreshMetadata(None, None, None, None, None, None)
            if metadata_row is None
            else EarningsRefreshMetadata(
                last_attempt_at=metadata_row["last_attempt_at"],
                last_success_at=metadata_row["last_success_at"],
                last_success_date=metadata_row["last_success_date"],
                outcome=metadata_row["outcome"],
                error_category=metadata_row["error_category"],
                next_eligible_retry_at=metadata_row["next_eligible_retry_at"],
            )
        )
        return rows, metadata

    def get_calendar_cache(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker, earnings_date
                FROM earnings_calendar_cache
                ORDER BY ticker ASC
                """
            ).fetchall()
        return {row["ticker"]: row["earnings_date"] for row in rows}

    def record_refresh_attempt(
        self,
        *,
        attempted_at: datetime | None = None,
        outcome: str,
        error_category: RefreshErrorCategory | None = None,
        next_eligible_retry_at: datetime | None = None,
        success_date: date | None = None,
    ) -> None:
        attempted_at_value = utc_timestamp(attempted_at)
        success_at = attempted_at_value if outcome == "success" else None
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT last_success_at, last_success_date
                FROM earnings_refresh_metadata
                WHERE id = 1
                """
            ).fetchone()
            connection.execute(
                """
                INSERT INTO earnings_refresh_metadata (
                    id,
                    last_attempt_at,
                    last_success_at,
                    last_success_date,
                    outcome,
                    error_category,
                    next_eligible_retry_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_success_at = excluded.last_success_at,
                    last_success_date = excluded.last_success_date,
                    outcome = excluded.outcome,
                    error_category = excluded.error_category,
                    next_eligible_retry_at = excluded.next_eligible_retry_at
                """,
                (
                    attempted_at_value,
                    success_at or (existing["last_success_at"] if existing else None),
                    success_date.isoformat()
                    if success_date
                    else (existing["last_success_date"] if existing else None),
                    outcome,
                    error_category,
                    utc_timestamp(next_eligible_retry_at)
                    if next_eligible_retry_at
                    else None,
                ),
            )

    def get_refresh_metadata(self) -> EarningsRefreshMetadata:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT last_attempt_at, last_success_at, last_success_date,
                       outcome, error_category, next_eligible_retry_at
                FROM earnings_refresh_metadata
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return EarningsRefreshMetadata(None, None, None, None, None, None)
        return EarningsRefreshMetadata(
            last_attempt_at=row["last_attempt_at"],
            last_success_at=row["last_success_at"],
            last_success_date=row["last_success_date"],
            outcome=row["outcome"],
            error_category=row["error_category"],
            next_eligible_retry_at=row["next_eligible_retry_at"],
        )

def utc_timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat()


def earnings_watch_row_from_row(row: sqlite3.Row) -> EarningsWatchRow:
    return EarningsWatchRow(
        ticker=row["ticker"],
        reviewed=bool(row["reviewed"]),
        earnings_date=row["earnings_date"],
        provider_refresh_date=row["provider_refresh_date"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
