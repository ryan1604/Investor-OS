import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.portfolio.flex import FlexClient, FlexError
from app.portfolio.nav_store import DailyNavStore, SYNC_ERRORS


class NavSyncService:
    def __init__(self, store: DailyNavStore, client: FlexClient | None, *,
                 interval_seconds: float = 3600, clock=None):
        self.store = store
        self.client = client
        self.interval_seconds = interval_seconds
        self.clock = clock or (lambda: datetime.now(ZoneInfo("America/New_York")).date())
        self.task: asyncio.Task | None = None
        self.syncing = False
        self.error: str | None = None

    def start(self):
        if self.client is not None and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        if self.client:
            await self.client.aclose()

    async def _run(self):
        while True:
            await self.sync_once()
            await asyncio.sleep(self.interval_seconds)

    async def sync_once(self):
        if self.client is None or self.syncing:
            return
        self.syncing = True
        accounts = []
        try:
            accounts = await asyncio.to_thread(self.store.list_accounts)
            start = end = None
            if accounts:
                histories = [await asyncio.to_thread(self.store.history, account) for account in accounts]
                oldest_latest = min(datetime.fromisoformat(h.latest_report_date).date() for h in histories)
                # Re-fetch a recent overlap for corrections; advance long gaps in bounded chunks.
                start = oldest_latest - timedelta(days=7)
                end = min(start + timedelta(days=30), self.clock() - timedelta(days=1))
                while end.weekday() > 4:
                    end -= timedelta(days=1)
                if start > end:
                    return
            values = await self.client.fetch(start, end)
            returned = {v.account for v in values}
            if not returned or (accounts and returned != set(accounts)):
                raise FlexError("invalid_report")
            if any(datetime.fromisoformat(v.report_date).date() >= self.clock() for v in values):
                raise FlexError("invalid_report")
            if start and any(not any(v.account == account and v.report_date >= start.isoformat() for v in values)
                             for account in accounts):
                raise FlexError("invalid_report")
            if not accounts:
                # Initial sync seeds latest completed values only, not inception history.
                latest = {account: max(v.report_date for v in values if v.account == account) for account in returned}
                values = [v for v in values if v.report_date == latest[v.account]]
            await asyncio.to_thread(self.store.upsert_values, values)
            for account in returned:
                await asyncio.to_thread(self.store.record_sync, account)
            self.error = None
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = error.code if isinstance(error, FlexError) else "invalid_report" if isinstance(error, ValueError) else "unavailable"
            self.error = SYNC_ERRORS[code]
            for account in accounts:
                # Persistence failure must not kill the scheduled retry loop.
                with suppress(Exception):
                    await asyncio.to_thread(self.store.record_sync, account, error=code)
        finally:
            self.syncing = False
