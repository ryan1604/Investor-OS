from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.sqlite import RowDatabase


@dataclass(frozen=True)
class BetaEstimate:
    """A computed beta; None when history was too short or flat."""

    beta: float | None
    observations: int


@dataclass(frozen=True)
class BetaOverride:
    ticker: str
    beta: float
    updated_at: str


class BetaStore(RowDatabase):
    """Per-session computed betas (latest session per ticker) and user overrides."""

    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS beta_cache (
                    ticker TEXT PRIMARY KEY,
                    session_date TEXT NOT NULL,
                    beta REAL,
                    observations INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS beta_overrides (
                    ticker TEXT PRIMARY KEY,
                    beta REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def cached_betas(self, session_date: str) -> dict[str, BetaEstimate]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker, beta, observations FROM beta_cache WHERE session_date = ?",
                (session_date,),
            ).fetchall()
        return {
            row["ticker"]: BetaEstimate(beta=row["beta"], observations=row["observations"])
            for row in rows
        }

    def save_cached_beta(
        self,
        ticker: str,
        session_date: str,
        estimate: BetaEstimate,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO beta_cache (ticker, session_date, beta, observations)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (ticker) DO UPDATE SET
                    session_date = excluded.session_date,
                    beta = excluded.beta,
                    observations = excluded.observations
                """,
                (ticker, session_date, estimate.beta, estimate.observations),
            )

    def list_overrides(self) -> list[BetaOverride]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT ticker, beta, updated_at FROM beta_overrides ORDER BY ticker"
            ).fetchall()
        return [
            BetaOverride(ticker=row["ticker"], beta=row["beta"], updated_at=row["updated_at"])
            for row in rows
        ]

    def override_betas(self) -> dict[str, float]:
        return {override.ticker: override.beta for override in self.list_overrides()}

    def set_override(self, ticker: str, beta: float) -> BetaOverride:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO beta_overrides (ticker, beta, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT (ticker) DO UPDATE SET
                    beta = excluded.beta,
                    updated_at = excluded.updated_at
                """,
                (ticker, beta, updated_at),
            )
        return BetaOverride(ticker=ticker, beta=beta, updated_at=updated_at)

    def delete_override(self, ticker: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM beta_overrides WHERE ticker = ?",
                (ticker,),
            )
        return cursor.rowcount > 0
