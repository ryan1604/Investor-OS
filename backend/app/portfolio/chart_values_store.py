import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.sqlite import RowDatabase


@dataclass(frozen=True)
class PortfolioChartValue:
    account: str
    month: str
    portfolio_value: float | None
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
                    portfolio_value REAL,
                    amount_invested REAL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account, month)
                )
                """
            )

    def list_values(self, account: str) -> list[PortfolioChartValue]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT account, month, portfolio_value, amount_invested, updated_at
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
                    portfolio_value,
                    amount_invested,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        account,
                        value.month,
                        value.portfolio_value,
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
        portfolio_value=row["portfolio_value"],
        amount_invested=row["amount_invested"],
        updated_at=row["updated_at"],
    )
