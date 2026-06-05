import asyncio

from app.portfolio.service import PortfolioRefreshService, PortfolioSnapshotCache
from app.schemas import IbStatus, PortfolioResponse


def empty_snapshot() -> PortfolioResponse:
    return PortfolioResponse(
        status=IbStatus(
            connected=True,
            host="127.0.0.1",
            port=7497,
            client_id=1,
        ),
        positions=[],
    )


def test_account_summaries_refresh_each_cycle():
    summary_refreshes = 0

    def refresh_account_summaries() -> None:
        nonlocal summary_refreshes
        summary_refreshes += 1

    service = PortfolioRefreshService(
        PortfolioSnapshotCache(empty_snapshot()),
        empty_snapshot,
        refresh_account_summaries=refresh_account_summaries,
    )

    async def exercise_service() -> None:
        await service.refresh_summaries()
        await service.refresh_summaries()

    asyncio.run(exercise_service())

    assert summary_refreshes == 2


def test_initial_snapshot_publishes_before_account_summary_refresh():
    summary_refreshes = 0
    published_summary_counts: list[int] = []

    def refresh() -> PortfolioResponse:
        published_summary_counts.append(summary_refreshes)
        return empty_snapshot()

    def refresh_account_summaries() -> None:
        nonlocal summary_refreshes
        summary_refreshes += 1

    service = PortfolioRefreshService(
        PortfolioSnapshotCache(empty_snapshot()),
        refresh,
        refresh_interval_seconds=60,
        refresh_account_summaries=refresh_account_summaries,
    )

    async def exercise_service() -> None:
        service.start()
        while not published_summary_counts:
            await asyncio.sleep(0)
        while summary_refreshes < 1:
            await asyncio.sleep(0)
        await service.stop()

    asyncio.run(exercise_service())

    assert published_summary_counts == [0]
    assert summary_refreshes == 1


def test_portfolio_refresh_reuses_snapshot_for_many_subscribers():
    refreshed_snapshot = empty_snapshot()
    service = PortfolioRefreshService(
        PortfolioSnapshotCache(empty_snapshot()),
        lambda: refreshed_snapshot,
        refresh_account_summaries=None,
    )

    async def exercise_service() -> list[PortfolioResponse]:
        subscribers = [service.subscribe()[1] for _ in range(25)]
        await service.refresh_snapshot()
        return [subscriber.get_nowait() for subscriber in subscribers]

    published_snapshots = asyncio.run(exercise_service())

    assert all(snapshot is refreshed_snapshot for snapshot in published_snapshots)
    assert service.cache.get() is refreshed_snapshot
