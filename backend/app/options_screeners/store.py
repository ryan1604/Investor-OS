import json
import re
import sqlite3
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from app.schemas import (
    CreditSpreadScreenerFilters,
    OptionsScreener,
    OptionsScreenerFilters,
    OptionsScreenerTickerList,
)
from app.sqlite import connect_row_database

TICKER_PATTERN = re.compile(r"^[A-Z0-9.-]+$")
TICKER_SEPARATOR_PATTERN = re.compile(r"[\s,]+")


class OptionsScreenerSettingsStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ticker_lists (
                    list_name TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    PRIMARY KEY (list_name, position),
                    UNIQUE (list_name, ticker)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS screener_filters (
                    screener TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    settings_json TEXT NOT NULL
                )
                """
            )

    def get_ticker_list(self, list_name: OptionsScreenerTickerList) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ticker
                FROM ticker_lists
                WHERE list_name = ?
                ORDER BY position ASC
                """,
                (list_name,),
            ).fetchall()
        return [cast(str, row["ticker"]) for row in rows]

    def replace_ticker_list(
        self,
        list_name: OptionsScreenerTickerList,
        tickers: list[str],
    ) -> list[str]:
        normalized_tickers = normalize_tickers(tickers)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM ticker_lists WHERE list_name = ?",
                (list_name,),
            )
            connection.executemany(
                """
                INSERT INTO ticker_lists (list_name, position, ticker)
                VALUES (?, ?, ?)
                """,
                [
                    (list_name, position, ticker)
                    for position, ticker in enumerate(normalized_tickers)
                ],
            )
        return normalized_tickers

    def get_filters(
        self,
        screener: OptionsScreener,
    ) -> OptionsScreenerFilters | CreditSpreadScreenerFilters:
        model_type = filter_model_type(screener)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT settings_json
                FROM screener_filters
                WHERE screener = ?
                """,
                (screener,),
            ).fetchone()

        if row is None:
            return model_type()

        try:
            payload = json.loads(row["settings_json"])
            if not isinstance(payload, dict):
                return model_type()
            # Local settings are migration-tolerant: missing fields take current
            # schema defaults, and unreadable saved payloads reset to defaults.
            return model_type.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError):
            return model_type()

    def save_filters(
        self,
        screener: OptionsScreener,
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
    ) -> OptionsScreenerFilters | CreditSpreadScreenerFilters:
        model_type = filter_model_type(screener)
        saved_filters = model_type.model_validate(filters.model_dump())
        payload = saved_filters.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO screener_filters (screener, version, settings_json)
                VALUES (?, ?, ?)
                ON CONFLICT(screener) DO UPDATE SET
                    version = excluded.version,
                    settings_json = excluded.settings_json
                """,
                (screener, saved_filters.version, payload),
            )
        return saved_filters

    def get_settings(
        self,
    ) -> tuple[
        dict[OptionsScreenerTickerList, list[str]],
        dict[
            OptionsScreener,
            OptionsScreenerFilters | CreditSpreadScreenerFilters,
        ],
    ]:
        return (
            {
                "csp_cc": self.get_ticker_list("csp_cc"),
                "cs": self.get_ticker_list("cs"),
            },
            {
                "csp": self.get_filters("csp"),
                "cc": self.get_filters("cc"),
                "cs": self.get_filters("cs"),
            },
        )

    def _connect(self) -> sqlite3.Connection:
        return connect_row_database(self.database_path)


def normalize_tickers(values: list[str]) -> list[str]:
    normalized_tickers: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in TICKER_SEPARATOR_PATTERN.split(value.strip()):
            ticker = token.upper()
            if not ticker:
                continue
            if not TICKER_PATTERN.fullmatch(ticker):
                raise ValueError(
                    f"Invalid ticker '{token}'. "
                    "Tickers may contain only letters, numbers, '.' and '-'."
                )
            if ticker not in seen:
                seen.add(ticker)
                normalized_tickers.append(ticker)
    return normalized_tickers


def filter_model_type(
    screener: OptionsScreener,
) -> type[OptionsScreenerFilters] | type[CreditSpreadScreenerFilters]:
    if screener == "cs":
        return CreditSpreadScreenerFilters
    return OptionsScreenerFilters
