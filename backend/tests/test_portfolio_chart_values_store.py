from datetime import UTC, datetime
import sqlite3

import pytest

from app.portfolio.chart_values_store import (
    PortfolioChartValue,
    PortfolioChartValuesStore,
)


def make_store(tmp_path):
    return PortfolioChartValuesStore(tmp_path / "portfolio-chart-values.sqlite3")


def test_list_values_returns_empty_rows_for_unknown_account(tmp_path):
    store = make_store(tmp_path)

    assert store.list_values("DU1234567") == []


def test_replace_values_saves_rows_ordered_by_month(tmp_path):
    store = make_store(tmp_path)

    rows = store.replace_values(
        "DU1234567",
        [
            PortfolioChartValue("DU1234567", "2026-03", 1300.25, None, ""),
            PortfolioChartValue("DU1234567", "2026-01", None, 1000.0, ""),
        ],
        updated_at=datetime(2026, 6, 6, 1, 2, 3, tzinfo=UTC),
    )

    assert [row.month for row in rows] == ["2026-01", "2026-03"]
    assert rows[0].amount_invested == 1000.0
    assert rows[1].portfolio_value == 1300.25
    assert rows[0].updated_at == "2026-06-06T01:02:03+00:00"


def test_replace_values_only_replaces_selected_account(tmp_path):
    store = make_store(tmp_path)
    store.replace_values(
        "DU1234567",
        [PortfolioChartValue("DU1234567", "2026-01", 1000.0, 900.0, "")],
    )
    store.replace_values(
        "DU7654321",
        [PortfolioChartValue("DU7654321", "2026-02", 2000.0, 1800.0, "")],
    )

    store.replace_values(
        "DU1234567",
        [PortfolioChartValue("DU1234567", "2026-03", 1100.0, 950.0, "")],
    )

    first_account_rows = store.list_values("DU1234567")
    second_account_rows = store.list_values("DU7654321")
    assert [row.month for row in first_account_rows] == ["2026-03"]
    assert [row.month for row in second_account_rows] == ["2026-02"]


def test_replace_values_rolls_back_when_insert_fails(tmp_path):
    store = make_store(tmp_path)
    store.replace_values(
        "DU1234567",
        [PortfolioChartValue("DU1234567", "2026-01", 1000.0, 900.0, "")],
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.replace_values(
            "DU1234567",
            [
                PortfolioChartValue("DU1234567", "2026-02", 1100.0, 900.0, ""),
                PortfolioChartValue("DU1234567", "2026-02", 1200.0, 950.0, ""),
            ],
        )

    rows = store.list_values("DU1234567")
    assert [row.month for row in rows] == ["2026-01"]
