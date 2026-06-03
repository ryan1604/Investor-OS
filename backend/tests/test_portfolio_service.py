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
