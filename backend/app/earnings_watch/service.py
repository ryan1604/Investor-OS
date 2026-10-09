import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.earnings_watch.provider import (
    NEW_YORK,
    EarningsCalendarProvider,
    EarningsCalendarProviderError,
)
from app.earnings_watch.store import (
    EarningsRefreshMetadata,
    EarningsWatchRow,
    EarningsWatchStore,
)
from app.schemas import (
    EarningsWatchAddTickersResponse,
    EarningsWatchRefreshState,
    EarningsWatchResponse,
    EarningsWatchRowResponse,
    EarningsWatchRowStatus,
    EarningsWatchStateResponse,
)
from app.tickers import parse_ticker_tokens

REFRESH_COOLDOWN = timedelta(hours=1)


@dataclass(frozen=True)
class ParsedTickerBatch:
    tickers: list[str]
    rejected: list[str]


class EarningsWatchService:
    def __init__(
        self,
        store: EarningsWatchStore,
        provider: EarningsCalendarProvider,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(UTC))
        self._mutation_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None

    async def state(self, *, start_due_refresh: bool) -> EarningsWatchResponse:
        async with self._mutation_lock:
            rows, metadata = self.store.snapshot()
        if start_due_refresh:
            await self.start_refresh_if_due(metadata)
            metadata = refresh_metadata_with_active_state(
                metadata,
                self._refresh_task,
            )
        return self.response(rows, metadata)

    async def add_tickers(self, raw_text: str) -> EarningsWatchAddTickersResponse:
        parsed = parse_ticker_batch(raw_text)
        async with self._mutation_lock:
            before = {row.ticker for row in self.store.list_watchlist()}
            rows, existing = self.store.add_tickers(parsed.tickers, now=self.clock())
        added = [ticker for ticker in parsed.tickers if ticker not in before]
        return EarningsWatchAddTickersResponse(
            added=added,
            existing=existing,
            rejected=parsed.rejected,
            rows=[self.row_response(row) for row in rows],
        )

    async def remove_ticker(self, ticker: str) -> EarningsWatchRowResponse:
        async with self._mutation_lock:
            removed = self.store.remove_ticker(ticker)
        return self.row_response(removed)

    async def set_reviewed(
        self,
        ticker: str,
        reviewed: bool,
    ) -> EarningsWatchRowResponse:
        async with self._mutation_lock:
            row = self.store.set_reviewed(ticker, reviewed, now=self.clock())
        return self.row_response(row)

    async def clear_reviewed(self) -> EarningsWatchStateResponse:
        async with self._mutation_lock:
            rows = self.store.clear_reviewed(now=self.clock())
        return EarningsWatchStateResponse(rows=[self.row_response(row) for row in rows])

    async def start_refresh_if_due(self, metadata: EarningsRefreshMetadata) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        if not refresh_due(metadata, now=self.clock()):
            return
        async with self._refresh_lock:
            if self._refresh_task is None or self._refresh_task.done():
                self._refresh_task = asyncio.create_task(self.refresh())

    async def refresh(self) -> None:
        now = self.clock()
        today = now.astimezone(NEW_YORK).date()
        try:
            entries = await self.provider.fetch_calendar(today=today)
        except EarningsCalendarProviderError as error:
            async with self._mutation_lock:
                self.store.record_refresh_attempt(
                    attempted_at=self.clock(),
                    outcome="failed",
                    error_category=error.category,
                    next_eligible_retry_at=self.clock() + REFRESH_COOLDOWN,
                )
            return

        async with self._mutation_lock:
            fetched_at = self.clock()
            self.store.replace_calendar_cache(
                entries,
                provider_refresh_date=today,
                fetched_at=fetched_at,
            )
            self.store.record_refresh_attempt(
                attempted_at=fetched_at,
                outcome="success",
                success_date=today,
            )

    async def stop(self) -> None:
        task = self._refresh_task
        if task is None or task.done():
            return
        await task

    def response(
        self,
        rows: list[EarningsWatchRow],
        metadata: EarningsRefreshMetadata,
    ) -> EarningsWatchResponse:
        return EarningsWatchResponse(
            rows=[self.row_response(row) for row in rows],
            refresh=refresh_response(metadata, now=self.clock()),
        )

    def row_response(self, row: EarningsWatchRow) -> EarningsWatchRowResponse:
        return EarningsWatchRowResponse(
            ticker=row.ticker,
            reviewed=row.reviewed,
            earnings_date=row.earnings_date,
            status=row_status(row, today=self.clock().astimezone(NEW_YORK).date()),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def parse_ticker_batch(raw_text: str) -> ParsedTickerBatch:
    tickers, rejected = parse_ticker_tokens(raw_text)
    return ParsedTickerBatch(tickers=tickers, rejected=rejected)


def refresh_due(metadata: EarningsRefreshMetadata, *, now: datetime) -> bool:
    today = now.astimezone(NEW_YORK).date().isoformat()
    if metadata.last_success_date == today:
        return False
    next_retry = parse_datetime(metadata.next_eligible_retry_at)
    return next_retry is None or next_retry <= now.astimezone(UTC)


def refresh_metadata_with_active_state(
    metadata: EarningsRefreshMetadata,
    task: asyncio.Task[None] | None,
) -> EarningsRefreshMetadata:
    if task is None or task.done():
        return metadata
    return EarningsRefreshMetadata(
        last_attempt_at=metadata.last_attempt_at,
        last_success_at=metadata.last_success_at,
        last_success_date=metadata.last_success_date,
        outcome="refreshing",
        error_category=metadata.error_category,
        next_eligible_retry_at=metadata.next_eligible_retry_at,
    )


def refresh_response(
    metadata: EarningsRefreshMetadata,
    *,
    now: datetime,
) -> EarningsWatchRefreshState:
    state = refresh_state(metadata, now=now)
    return EarningsWatchRefreshState(
        state=state,
        last_attempt_at=metadata.last_attempt_at,
        last_success_at=metadata.last_success_at,
        last_success_date=metadata.last_success_date,
        error_category=metadata.error_category,
        next_eligible_retry_at=metadata.next_eligible_retry_at,
    )


def refresh_state(
    metadata: EarningsRefreshMetadata,
    *,
    now: datetime,
) -> str:
    if metadata.outcome == "refreshing":
        return "refreshing"
    next_retry = parse_datetime(metadata.next_eligible_retry_at)
    if metadata.outcome == "failed" and next_retry is not None and next_retry > now:
        return "cooldown"
    if metadata.outcome == "success":
        return "succeeded"
    if metadata.outcome == "failed":
        return "failed"
    return "never_attempted"


def row_status(row: EarningsWatchRow, *, today: date) -> EarningsWatchRowStatus:
    if row.earnings_date is None:
        return "no_date"
    try:
        earnings_date = date.fromisoformat(row.earnings_date)
    except ValueError:
        return "last_known"
    if earnings_date >= today and row.provider_refresh_date == today.isoformat():
        return "upcoming"
    return "last_known"


def parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
