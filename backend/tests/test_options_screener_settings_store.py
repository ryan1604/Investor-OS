import json
import sqlite3

import pytest

from app.options_screeners.store import OptionsScreenerSettingsStore
from app.schemas import CreditSpreadScreenerFilters, OptionsScreenerFilters


@pytest.fixture
def store(tmp_path):
    return OptionsScreenerSettingsStore(tmp_path / "options-screeners.sqlite3")


def test_ticker_lists_are_ordered_normalized_deduplicated_and_independent(store):
    csp_cc = store.replace_ticker_list(
        "csp_cc",
        [" aapl, msft ", "BRK.b\nAAPL", "RDS-A"],
    )
    cs = store.replace_ticker_list("cs", ["spy", "qqq"])

    assert csp_cc == ["AAPL", "MSFT", "BRK.B", "RDS-A"]
    assert store.get_ticker_list("csp_cc") == csp_cc
    assert store.get_ticker_list("cs") == cs


def test_ticker_list_replacement_rejects_invalid_tokens_without_changing_rows(store):
    store.replace_ticker_list("csp_cc", ["AAPL", "MSFT"])

    with pytest.raises(ValueError, match="Invalid ticker"):
        store.replace_ticker_list("csp_cc", ["NVDA", "BAD/TICKER"])

    assert store.get_ticker_list("csp_cc") == ["AAPL", "MSFT"]


def test_filters_default_and_save_independently(store):
    assert store.get_filters("csp") == OptionsScreenerFilters()
    assert store.get_filters("cc") == OptionsScreenerFilters()
    assert store.get_filters("cs") == CreditSpreadScreenerFilters()

    csp = OptionsScreenerFilters(minimum_dte=14, maximum_dte=30)
    cc = OptionsScreenerFilters(minimum_annualized_return=20)
    cs = CreditSpreadScreenerFilters(
        strategy_types=["put_credit_spread"],
        spread_widths=[2.5, 5.0],
    )

    store.save_filters("csp", csp)
    store.save_filters("cc", cc)
    store.save_filters("cs", cs)

    assert store.get_filters("csp") == csp
    assert store.get_filters("cc") == cc
    assert store.get_filters("cs") == cs


def test_settings_survive_store_recreation(tmp_path):
    database_path = tmp_path / "options-screeners.sqlite3"
    store = OptionsScreenerSettingsStore(database_path)
    store.replace_ticker_list("csp_cc", ["AAPL", "MSFT"])
    store.save_filters(
        "csp",
        OptionsScreenerFilters(minimum_annualized_return=15),
    )

    reopened_store = OptionsScreenerSettingsStore(database_path)

    assert reopened_store.get_ticker_list("csp_cc") == ["AAPL", "MSFT"]
    assert reopened_store.get_filters("csp").minimum_annualized_return == 15


def test_legacy_partial_filter_payload_uses_current_defaults(tmp_path):
    database_path = tmp_path / "options-screeners.sqlite3"
    store = OptionsScreenerSettingsStore(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO screener_filters (screener, version, settings_json)
            VALUES (?, ?, ?)
            """,
            ("csp", 1, json.dumps({"version": 1, "minimum_dte": 12})),
        )

    filters = store.get_filters("csp")

    assert filters.minimum_dte == 12
    assert filters.maximum_dte == 45
    assert filters.minimum_absolute_delta == 0.15
    assert filters.minimum_annualized_return == 10


def test_invalid_stored_filter_payload_falls_back_to_defaults(tmp_path):
    database_path = tmp_path / "options-screeners.sqlite3"
    store = OptionsScreenerSettingsStore(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO screener_filters (screener, version, settings_json)
            VALUES (?, ?, ?)
            """,
            ("cs", 1, '{"strategy_types": []}'),
        )

    assert store.get_filters("cs") == CreditSpreadScreenerFilters()


def test_database_only_contains_settings_tables(store):
    with sqlite3.connect(store.database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

    assert table_names == {"ticker_lists", "screener_filters"}
