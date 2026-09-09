import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.sqlite import RowDatabase


@dataclass(frozen=True)
class PortfolioChartValue:
    account: str
    month: str
    amount_invested: float | None
    updated_at: str


class PortfolioChartValuesStore(RowDatabase):
    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_chart_values (
                    account TEXT NOT NULL,
                    month TEXT NOT NULL,
                    amount_invested REAL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account, month)
                )
                """
            )

            columns = {row["name"] for row in connection.execute("PRAGMA table_info(portfolio_chart_values)")}
            if "portfolio_value" in columns:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM portfolio_chart_values WHERE amount_invested IS NULL")
                connection.execute("ALTER TABLE portfolio_chart_values DROP COLUMN portfolio_value")

    def list_values(self, account: str) -> list[PortfolioChartValue]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT account, month, amount_invested, updated_at
                FROM portfolio_chart_values
                WHERE account = ?
                ORDER BY month ASC
                """,
                (account,),
            ).fetchall()

        return [portfolio_chart_value_from_row(row) for row in rows]

    def replace_values(
        self,
        account: str,
        values: list[PortfolioChartValue],
        *,
        updated_at: datetime | None = None,
    ) -> list[PortfolioChartValue]:
        updated_at_value = (updated_at or datetime.now(UTC)).isoformat()

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM portfolio_chart_values WHERE account = ?",
                (account,),
            )
            connection.executemany(
                """
                INSERT INTO portfolio_chart_values (
                    account,
                    month,
                    amount_invested,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        account,
                        value.month,
                        value.amount_invested,
                        updated_at_value,
                    )
                    for value in values
                ],
            )

        return self.list_values(account)

def portfolio_chart_value_from_row(row: sqlite3.Row) -> PortfolioChartValue:
    return PortfolioChartValue(
        account=row["account"],
        month=row["month"],
        amount_invested=row["amount_invested"],
        updated_at=row["updated_at"],
    )
