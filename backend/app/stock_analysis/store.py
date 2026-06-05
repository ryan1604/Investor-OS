import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from app.schemas import StockAnalysisPayload
from app.tickers import normalize_ticker


@dataclass(frozen=True)
class StockAnalysisModel:
    ticker: str
    version: int
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
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get_model(self, ticker: str) -> StockAnalysisModel | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ticker, version, payload_json, updated_at
                FROM stock_analysis_models
                WHERE ticker = ?
                """,
                (normalize_ticker(ticker),),
            ).fetchone()

        if row is None:
            return None

        return StockAnalysisModel(
            ticker=row["ticker"],
            version=row["version"],
            payload=cast(StockAnalysisPayload, json.loads(row["payload_json"])),
            updated_at=row["updated_at"],
        )

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
                    payload_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    version = excluded.version,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (normalized_ticker, version, payload_json, updated_at_value),
            )

        return StockAnalysisModel(
            ticker=normalized_ticker,
            version=version,
            payload=payload,
            updated_at=updated_at_value,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection
