import asyncio
import logging
import threading
from collections.abc import Callable

from app.schemas import PortfolioResponse

logger = logging.getLogger(__name__)


class PortfolioSnapshotCache:
    def __init__(self, snapshot: PortfolioResponse) -> None:
        self.lock = threading.Lock()
        self.snapshot = snapshot

    def get(self) -> PortfolioResponse:
        with self.lock:
            return self.snapshot.model_copy(deep=True)

    def set(self, snapshot: PortfolioResponse) -> None:
        with self.lock:
            self.snapshot = snapshot.model_copy(deep=True)


class PortfolioRefreshService:
    def __init__(
        self,
        cache: PortfolioSnapshotCache,
        refresh: Callable[[], PortfolioResponse],
        *,
        refresh_interval_seconds: float = 3,
        refresh_account_summaries: Callable[[], None] | None = None,
    ) -> None:
        self.cache = cache
        self.refresh = refresh
        self.refresh_interval_seconds = refresh_interval_seconds
        self.refresh_account_summaries = refresh_account_summaries
        self.subscribers: set[asyncio.Queue[PortfolioResponse]] = set()
        self.task: asyncio.Task[None] | None = None
        self.stop_requested = asyncio.Event()

    def start(self) -> None:
        self.stop_requested.clear()
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task is None:
            return

        self.stop_requested.set()
        await self.task
        self.task = None

    def subscribe(
        self,
    ) -> tuple[PortfolioResponse, asyncio.Queue[PortfolioResponse]]:
        queue: asyncio.Queue[PortfolioResponse] = asyncio.Queue(maxsize=1)
        self.subscribers.add(queue)
        return self.cache.get(), queue

    def unsubscribe(self, queue: asyncio.Queue[PortfolioResponse]) -> None:
        self.subscribers.discard(queue)

    async def run(self) -> None:
        while not self.stop_requested.is_set():
            await self.refresh_summaries()

            try:
                snapshot = await asyncio.to_thread(self.refresh)
            except Exception:
                logger.exception("Could not refresh Portfolio snapshot")
            else:
                if self.stop_requested.is_set():
                    break

                self.cache.set(snapshot)

                for queue in self.subscribers:
                    if queue.full():
                        queue.get_nowait()

                    queue.put_nowait(snapshot.model_copy(deep=True))

            try:
                await asyncio.wait_for(
                    self.stop_requested.wait(),
                    timeout=self.refresh_interval_seconds,
                )
            except TimeoutError:
                pass

    async def refresh_summaries(self) -> None:
        if self.refresh_account_summaries is None:
            return

        try:
            await asyncio.to_thread(self.refresh_account_summaries)
        except Exception:
            logger.exception("Could not refresh Portfolio account summaries")
