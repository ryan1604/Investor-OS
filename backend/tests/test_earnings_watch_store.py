from datetime import UTC, date, datetime

from app.earnings_watch.store import EarningsWatchStore


def make_store(tmp_path):
    return EarningsWatchStore(tmp_path / "earnings-watch.sqlite3")


def test_watchlist_rows_persist_review_state_and_order(tmp_path):
    store = make_store(tmp_path)
    store.add_ticker(" msft ", now=datetime(2026, 6, 1, tzinfo=UTC))
    store.add_ticker("brk.b", now=datetime(2026, 6, 2, tzinfo=UTC))
    store.set_reviewed("MSFT", True, now=datetime(2026, 6, 3, tzinfo=UTC))

    reopened = make_store(tmp_path)
    rows = reopened.list_watchlist()

    assert [row.ticker for row in rows] == ["MSFT", "BRK.B"]
    assert rows[0].reviewed is True
    assert rows[1].reviewed is False


def test_batch_add_is_transactional_and_duplicate_additions_are_noops(tmp_path):
    store = make_store(tmp_path)

    try:
        store.add_tickers(["AAPL", " "], now=datetime(2026, 6, 1, tzinfo=UTC))
    except ValueError:
        pass

    assert store.list_watchlist() == []

    rows, existing = store.add_tickers(
        ["MSFT", "MSFT"],
        now=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert [row.ticker for row in rows] == ["MSFT"]
    assert existing == ["MSFT"]


def test_calendar_cache_updates_watchlist_snapshots_without_recreating_removed_rows(tmp_path):
    store = make_store(tmp_path)
    store.add_ticker("AAPL", now=datetime(2026, 6, 1, tzinfo=UTC))
    store.add_ticker("MSFT", now=datetime(2026, 6, 2, tzinfo=UTC))

    store.replace_calendar_cache(
        {"AAPL": date(2026, 7, 30), "TSLA": date(2026, 8, 1)},
        provider_refresh_date=date(2026, 6, 18),
        fetched_at=datetime(2026, 6, 18, 12, tzinfo=UTC),
    )

    rows = {row.ticker: row for row in store.list_watchlist()}
    assert rows["AAPL"].earnings_date == "2026-07-30"
    assert rows["AAPL"].provider_refresh_date == "2026-06-18"
    assert rows["MSFT"].earnings_date is None
    assert rows["MSFT"].provider_refresh_date is None
    assert "TSLA" not in rows
    assert store.get_calendar_cache() == {
        "AAPL": "2026-07-30",
        "TSLA": "2026-08-01",
    }


def test_new_ticker_gets_existing_cache_snapshot(tmp_path):
    store = make_store(tmp_path)
    store.replace_calendar_cache(
        {"RDS-A": date(2026, 7, 15)},
        provider_refresh_date=date(2026, 6, 18),
        fetched_at=datetime(2026, 6, 18, tzinfo=UTC),
    )

    row = store.add_ticker("rds-a", now=datetime(2026, 6, 19, tzinfo=UTC))

    assert row.ticker == "RDS-A"
    assert row.earnings_date == "2026-07-15"
    assert row.provider_refresh_date == "2026-06-18"


def test_refresh_metadata_preserves_last_success_after_failure(tmp_path):
    store = make_store(tmp_path)
    store.record_refresh_attempt(
        attempted_at=datetime(2026, 6, 18, 12, tzinfo=UTC),
        outcome="success",
        success_date=date(2026, 6, 18),
    )
    store.record_refresh_attempt(
        attempted_at=datetime(2026, 6, 18, 13, tzinfo=UTC),
        outcome="failed",
        error_category="rate_limited",
        next_eligible_retry_at=datetime(2026, 6, 18, 14, tzinfo=UTC),
    )

    metadata = store.get_refresh_metadata()

    assert metadata.last_attempt_at == "2026-06-18T13:00:00+00:00"
    assert metadata.last_success_at == "2026-06-18T12:00:00+00:00"
    assert metadata.last_success_date == "2026-06-18"
    assert metadata.outcome == "failed"
    assert metadata.error_category == "rate_limited"
    assert metadata.next_eligible_retry_at == "2026-06-18T14:00:00+00:00"
