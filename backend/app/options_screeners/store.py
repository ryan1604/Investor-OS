import json
import re
import sqlite3
from pathlib import Path
from typing import cast

from app.schemas import (
    CreditSpreadScreenerFilters,
    OptionsScreener,
    OptionsScreenerFilters,
    OptionsScreenerTickerList,
)
from app.sqlite import RowDatabase

TICKER_PATTERN = re.compile(r"^[A-Z0-9.-]+$")
TICKER_SEPARATOR_PATTERN = re.compile(r"[\s,]+")


class OptionsScreenerSettingsStore(RowDatabase):
    def __init__(self, database_path: str | Path) -> None:
        super().__init__(database_path)
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

        payload = json.loads(row["settings_json"])
        if not isinstance(payload, dict) or set(payload) != set(
            model_type.model_fields
        ):
            raise ValueError("Saved screener filters use an unsupported schema.")
        return model_type.model_validate(payload)

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
