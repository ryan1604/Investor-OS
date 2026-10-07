from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.sqlite import RowDatabase


@dataclass(frozen=True)
class RiskLimit:
    key: str
    value: float
    updated_at: str


class RiskLimitsStore(RowDatabase):
    """User-set risk limits per account; an account with no rows has no limits."""

    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_limits (
                    account TEXT NOT NULL,
                    limit_key TEXT NOT NULL,
                    value REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account, limit_key)
                )
                """
            )

    def list_limits(self, account: str) -> list[RiskLimit]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT limit_key, value, updated_at FROM risk_limits
                WHERE account = ? ORDER BY limit_key
                """,
                (account,),
            ).fetchall()
        return [
            RiskLimit(key=row["limit_key"], value=row["value"], updated_at=row["updated_at"])
            for row in rows
        ]

    def replace_limits(self, account: str, limits: dict[str, float]) -> list[RiskLimit]:
        """Save exactly these limits for the account; keys left out are cleared."""
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM risk_limits WHERE account = ?", (account,))
            connection.executemany(
                """
                INSERT INTO risk_limits (account, limit_key, value, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                [(account, key, value, updated_at) for key, value in limits.items()],
            )
        return self.list_limits(account)
