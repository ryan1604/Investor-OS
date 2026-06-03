from datetime import UTC, date, datetime

from app.options.store import CompletedDailyBar, OptionsDailyBarStore


def make_store(tmp_path):
    return OptionsDailyBarStore(tmp_path / "options-bars.sqlite3")


def test_get_completed_bars_returns_empty_list_for_unknown_ticker(tmp_path):
    store = make_store(tmp_path)

    assert store.get_completed_bars("AAPL") == []


def test_upsert_completed_bars_inserts_and_reads_ticker_rows(tmp_path):
    store = make_store(tmp_path)

    store.upsert_completed_bars(
        [
            CompletedDailyBar(
                ticker="aapl",
                trading_date="2026-05-28",
                open=190,
                high=195,
                low=188,
                close=193,
                volume=1_250_000,
            )
        ],
        current_date=date(2026, 5, 30),
        fetched_at=datetime(2026, 5, 30, 1, 2, 3, tzinfo=UTC),
    )

    bars = store.get_completed_bars("AAPL")

    assert len(bars) == 1
    assert bars[0].ticker == "AAPL"
    assert bars[0].trading_date == "2026-05-28"
    assert bars[0].close == 193
    assert bars[0].volume == 1_250_000
    assert bars[0].fetched_at == "2026-05-30T01:02:03+00:00"


def test_get_completed_bars_filters_by_date_range(tmp_path):
    store = make_store(tmp_path)
    store.upsert_completed_bars(
        [
            CompletedDailyBar("MSFT", "2026-05-27", 100, 101, 99, 100, 1),
            CompletedDailyBar("MSFT", "2026-05-28", 101, 102, 100, 101, 2),
            CompletedDailyBar("MSFT", "2026-05-29", 102, 103, 101, 102, 3),
            CompletedDailyBar("AAPL", "2026-05-28", 200, 201, 199, 200, 4),
        ],
        current_date=date(2026, 5, 30),
    )

    bars = store.get_completed_bars(
        "MSFT",
        start_date="2026-05-28",
        end_date="2026-05-29",
    )

    assert [bar.trading_date for bar in bars] == ["2026-05-28", "2026-05-29"]
    assert [bar.close for bar in bars] == [101, 102]


def test_upsert_completed_bars_updates_existing_row(tmp_path):
    store = make_store(tmp_path)
    original = CompletedDailyBar("TSLA", "2026-05-28", 100, 101, 99, 100, 10)
    revised = CompletedDailyBar("TSLA", "2026-05-28", 100, 103, 98, 102, 20)

    store.upsert_completed_bars(
        [original],
        current_date=date(2026, 5, 30),
        fetched_at=datetime(2026, 5, 30, 1, 0, tzinfo=UTC),
    )
    store.upsert_completed_bars(
        [revised],
        current_date=date(2026, 5, 30),
        fetched_at=datetime(2026, 5, 30, 2, 0, tzinfo=UTC),
    )

    bars = store.get_completed_bars("TSLA")

    assert len(bars) == 1
    assert bars[0].high == 103
    assert bars[0].low == 98
    assert bars[0].close == 102
    assert bars[0].volume == 20
    assert bars[0].fetched_at == "2026-05-30T02:00:00+00:00"


def test_upsert_completed_bars_skips_current_trading_day(tmp_path):
    store = make_store(tmp_path)

    store.upsert_completed_bars(
        [
            CompletedDailyBar("NVDA", "2026-05-29", 100, 101, 99, 100, None),
            CompletedDailyBar("NVDA", "2026-05-30", 101, 102, 100, 101, None),
        ],
        current_date=date(2026, 5, 30),
    )

    bars = store.get_completed_bars("NVDA")

    assert [bar.trading_date for bar in bars] == ["2026-05-29"]
