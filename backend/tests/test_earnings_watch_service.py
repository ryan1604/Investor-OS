import asyncio
from datetime import UTC, date, datetime, timedelta

import anyio
import pytest

from app.earnings_watch.provider import EarningsCalendarProviderError
from app.earnings_watch.service import EarningsWatchService
from app.earnings_watch.store import EarningsWatchStore


def make_store(tmp_path):
    return EarningsWatchStore(tmp_path / "earnings-watch.sqlite3")


def test_batch_additions_report_added_existing_and_rejected_tokens(tmp_path):
    store = make_store(tmp_path)
    service = EarningsWatchService(
        store,
        StaticProvider({}),
        clock=lambda: datetime(2026, 6, 18, 12, tzinfo=UTC),
    )
    anyio.run(service.add_tickers, "aapl")

    response = anyio.run(service.add_tickers, "msft, AAPL\nbad/ticker brk.b msft")

    assert response.added == ["MSFT", "BRK.B"]
    assert response.existing == ["AAPL"]
    assert response.rejected == ["bad/ticker"]
    assert [row.ticker for row in response.rows] == ["AAPL", "MSFT", "BRK.B"]


def test_successful_refresh_suppresses_same_day_provider_requests(tmp_path):
    provider = StaticProvider({"AAPL": date(2026, 7, 30)})
    service = EarningsWatchService(
        make_store(tmp_path),
        provider,
        clock=lambda: datetime(2026, 6, 18, 12, tzinfo=UTC),
    )
    anyio.run(service.add_tickers, "AAPL")

    first = anyio.run(lambda: service.state(start_due_refresh=True))
    anyio.run(service.stop)
    second = anyio.run(lambda: service.state(start_due_refresh=True))

    assert provider.calls == 1
    assert first.refresh.state == "refreshing"
    assert second.refresh.state == "succeeded"
    assert second.rows[0].status == "upcoming"


def test_refresh_uses_new_york_day_and_treats_today_as_upcoming(tmp_path):
    current = datetime(2026, 6, 19, 3, 30, tzinfo=UTC)
    provider = StaticProvider({"AAPL": date(2026, 6, 18)})
    service = EarningsWatchService(
        make_store(tmp_path),
        provider,
        clock=lambda: current,
    )
    anyio.run(service.add_tickers, "AAPL")
    anyio.run(lambda: service.state(start_due_refresh=True))
    anyio.run(service.stop)

    response = anyio.run(lambda: service.state(start_due_refresh=False))

    assert provider.days == [date(2026, 6, 18)]
    assert response.rows[0].status == "upcoming"


def test_failed_refresh_preserves_dates_and_enters_persisted_cooldown(tmp_path):
    database_path = tmp_path / "earnings-watch.sqlite3"
    store = EarningsWatchStore(database_path)
    service = EarningsWatchService(
        store,
        StaticProvider({"AAPL": date(2026, 7, 30)}),
        clock=lambda: datetime(2026, 6, 18, 12, tzinfo=UTC),
    )
    anyio.run(service.add_tickers, "AAPL")
    anyio.run(lambda: service.state(start_due_refresh=True))
    anyio.run(service.stop)

    failed = EarningsWatchService(
        EarningsWatchStore(database_path),
        FailingProvider("rate_limited"),
        clock=lambda: datetime(2026, 6, 19, 12, tzinfo=UTC),
    )
    anyio.run(lambda: failed.state(start_due_refresh=True))
    anyio.run(failed.stop)

    restarted = EarningsWatchService(
        EarningsWatchStore(database_path),
        StaticProvider({"AAPL": date(2026, 8, 1)}),
        clock=lambda: datetime(2026, 6, 19, 12, 30, tzinfo=UTC),
    )
    response = anyio.run(lambda: restarted.state(start_due_refresh=True))

    assert response.refresh.state == "cooldown"
    assert response.refresh.error_category == "rate_limited"
    assert response.refresh.next_eligible_retry_at == "2026-06-19T13:00:00+00:00"
    assert response.rows[0].earnings_date == "2026-07-30"
    assert response.rows[0].reviewed is False
    assert response.rows[0].status == "last_known"


def test_failed_refresh_retries_after_one_hour(tmp_path):
    now = datetime(2026, 6, 18, 12, tzinfo=UTC)
    provider = FailingProvider("timeout")
    service = EarningsWatchService(
        make_store(tmp_path),
        provider,
        clock=lambda: now,
    )

    anyio.run(lambda: service.state(start_due_refresh=True))
    anyio.run(service.stop)

    retry = EarningsWatchService(
        service.store,
        provider,
        clock=lambda: now + timedelta(hours=1),
    )
    anyio.run(lambda: retry.state(start_due_refresh=True))
    anyio.run(retry.stop)

    assert provider.calls == 2


def test_concurrent_state_loads_share_one_refresh(tmp_path):
    provider = BlockingProvider({"AAPL": date(2026, 7, 30)})
    service = EarningsWatchService(
        make_store(tmp_path),
        provider,
        clock=lambda: datetime(2026, 6, 18, 12, tzinfo=UTC),
    )

    async def run_scenario():
        await asyncio.gather(
            service.state(start_due_refresh=True),
            service.state(start_due_refresh=True),
            service.state(start_due_refresh=True),
        )
        await provider.started.wait()
        provider.release.set()
        await service.stop()

    anyio.run(run_scenario)

    assert provider.calls == 1


def test_refresh_commit_respects_concurrent_mutations(tmp_path):
    provider = BlockingProvider(
        {"AAPL": date(2026, 7, 30), "MSFT": date(2026, 8, 1)}
    )
    service = EarningsWatchService(
        make_store(tmp_path),
        provider,
        clock=lambda: datetime(2026, 6, 18, 12, tzinfo=UTC),
    )
    anyio.run(service.add_tickers, "AAPL")

    async def run_scenario():
        await service.state(start_due_refresh=True)
        await provider.started.wait()
        await service.add_tickers("MSFT")
        await service.set_reviewed("MSFT", True)
        await service.remove_ticker("AAPL")
        provider.release.set()
        await service.stop()
        return await service.state(start_due_refresh=False)

    response = anyio.run(run_scenario)

    assert [row.ticker for row in response.rows] == ["MSFT"]
    assert response.rows[0].earnings_date == "2026-08-01"
    assert response.rows[0].reviewed is True


def test_missing_dates_keep_prior_snapshot_as_last_known(tmp_path):
    provider = MutableProvider({"AAPL": date(2026, 7, 30)})
    service = EarningsWatchService(
        make_store(tmp_path),
        provider,
        clock=lambda: datetime(2026, 6, 18, 12, tzinfo=UTC),
    )
    anyio.run(service.add_tickers, "AAPL")
    anyio.run(lambda: service.state(start_due_refresh=True))
    anyio.run(service.stop)

    provider.entries = {"MSFT": date(2026, 8, 1)}
    next_day = EarningsWatchService(
        service.store,
        provider,
        clock=lambda: datetime(2026, 6, 19, 12, tzinfo=UTC),
    )
    anyio.run(lambda: next_day.state(start_due_refresh=True))
    anyio.run(next_day.stop)
    response = anyio.run(lambda: next_day.state(start_due_refresh=False))

    assert response.rows[0].earnings_date == "2026-07-30"
    assert response.rows[0].status == "last_known"


class StaticProvider:
    def __init__(self, entries):
        self.entries = entries
        self.calls = 0
        self.days = []

    async def fetch_calendar(self, *, today=None):
        self.calls += 1
        self.days.append(today)
        if not self.entries:
            raise EarningsCalendarProviderError("invalid_response")
        return self.entries


class MutableProvider(StaticProvider):
    pass


class FailingProvider:
    def __init__(self, category: str):
        self.category = category
        self.calls = 0

    async def fetch_calendar(self, *, today=None):
        self.calls += 1
        raise EarningsCalendarProviderError(self.category)


class BlockingProvider(StaticProvider):
    def __init__(self, entries):
        super().__init__(entries)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch_calendar(self, *, today=None):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.entries
