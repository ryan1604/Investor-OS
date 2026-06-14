import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from app.schemas import StockAnalysisPayload, empty_stock_analysis_payload
from app.tickers import normalize_ticker


@dataclass(frozen=True)
class StockAnalysisModel:
    ticker: str
    version: int
    current_price: float | None
    payload: StockAnalysisPayload
    updated_at: str


class StockAnalysisStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_analysis_models (
                    ticker TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    current_price REAL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(stock_analysis_models)"
                ).fetchall()
            }
            if "current_price" not in columns:
                connection.execute(
                    "ALTER TABLE stock_analysis_models ADD COLUMN current_price REAL"
                )

    def get_model(self, ticker: str) -> StockAnalysisModel | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ticker, version, current_price, payload_json, updated_at
                FROM stock_analysis_models
                WHERE ticker = ?
                """,
                (normalize_ticker(ticker),),
            ).fetchone()

        if row is None:
            return None

        return stock_analysis_model_from_row(row)

    def list_models(self) -> list[StockAnalysisModel]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker, version, current_price, payload_json, updated_at
                FROM stock_analysis_models
                ORDER BY ticker ASC
                """
            ).fetchall()

        return [stock_analysis_model_from_row(row) for row in rows]

    def upsert_model(
        self,
        ticker: str,
        *,
        version: int,
        payload: StockAnalysisPayload,
        updated_at: datetime | None = None,
    ) -> StockAnalysisModel:
        normalized_ticker = normalize_ticker(ticker)
        updated_at_value = (updated_at or datetime.now(UTC)).isoformat()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO stock_analysis_models (
                    ticker,
                    version,
                    current_price,
                    payload_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    version = excluded.version,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_ticker,
                    version,
                    None,
                    payload_json,
                    updated_at_value,
                ),
            )

        model = self.get_model(normalized_ticker)
        if model is None:
            raise RuntimeError("Stock analysis model upsert did not persist.")
        return model

    def update_current_price(
        self,
        ticker: str,
        current_price: float,
        *,
        updated_at: datetime | None = None,
    ) -> StockAnalysisModel:
        normalized_ticker = normalize_ticker(ticker)
        updated_at_value = (updated_at or datetime.now(UTC)).isoformat()
        payload_json = json.dumps(
            empty_stock_analysis_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO stock_analysis_models (
                    ticker,
                    version,
                    current_price,
                    payload_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    current_price = excluded.current_price,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_ticker,
                    1,
                    current_price,
                    payload_json,
                    updated_at_value,
                ),
            )

        model = self.get_model(normalized_ticker)
        if model is None:
            raise RuntimeError("Stock analysis price update did not persist.")
        return model

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def stock_analysis_model_from_row(row: sqlite3.Row) -> StockAnalysisModel:
    return StockAnalysisModel(
        ticker=row["ticker"],
        version=row["version"],
        current_price=row["current_price"],
        payload=cast(StockAnalysisPayload, json.loads(row["payload_json"])),
        updated_at=row["updated_at"],
    )
