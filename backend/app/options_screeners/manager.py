from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import queue
import threading
from uuid import uuid4

from app.options_screeners.domain import sort_candidates
from app.options_screeners.service import (
    OptionsScreenerQuoteRefreshService,
    OptionsScreenerScanService,
    OptionsScreenerSpreadQuoteRefreshService,
    OptionsScreenerTickerResult,
)
from app.options_screeners.store import OptionsScreenerSettingsStore
from app.schemas import (
    CreditSpreadScreenerFilters,
    OptionsScreener,
    OptionsScreenerCompletedSnapshot,
    OptionsScreenerFilters,
    OptionsScreenerQuoteRefreshRequest,
    OptionsScreenerQuoteRefreshResponse,
    OptionsScreenerSpreadQuoteRefreshRequest,
    OptionsScreenerSpreadQuoteRefreshResponse,
    OptionsScreenerScanEvent,
    OptionsScreenerScanJob,
    OptionsScreenerScanState,
    OptionsScreenerTickerWarning,
)


class OptionsScreenerScanConflict(RuntimeError):
    def __init__(self, job: OptionsScreenerScanJob) -> None:
        self.job = job
        super().__init__(
            f"Scan {job.id} for {job.screener} is already active."
        )


class OptionsScreenerJobNotFound(KeyError):
    pass


class OptionsScreenerJobNotActive(RuntimeError):
    pass


class OptionsScreenerScanManager:
    def __init__(
        self,
        settings_store: OptionsScreenerSettingsStore,
        scan_services: Mapping[OptionsScreener, OptionsScreenerScanService],
        quote_refresh_service: OptionsScreenerQuoteRefreshService,
        spread_quote_refresh_service: OptionsScreenerSpreadQuoteRefreshService,
        *,
        max_workers: int = 4,
        retention_minutes: int = 30,
        subscriber_queue_size: int = 64,
    ) -> None:
        self.settings_store = settings_store
        self.scan_services = dict(scan_services)
        self.quote_refresh_service = quote_refresh_service
        self.spread_quote_refresh_service = spread_quote_refresh_service
        self.max_workers = max(1, max_workers)
        self.retention = timedelta(minutes=retention_minutes)
        self.subscriber_queue_size = max(1, subscriber_queue_size)
        self.lock = threading.RLock()
        self.jobs: dict[str, OptionsScreenerScanJob] = {}
        self.active_job_id: str | None = None
        self.latest_job_ids: dict[OptionsScreener, str | None] = {
            "csp": None,
            "cc": None,
            "cs": None,
        }
        self.completed_snapshots: dict[
            OptionsScreener,
            OptionsScreenerCompletedSnapshot | None,
        ] = {
            "csp": None,
            "cc": None,
            "cs": None,
        }
        self.cancel_events: dict[str, threading.Event] = {}
        self.subscribers: set[queue.Queue[OptionsScreenerScanEvent]] = set()
        self.threads: set[threading.Thread] = set()

    def start(self, screener: OptionsScreener) -> OptionsScreenerScanJob:
        with self.lock:
            self._purge_expired_locked()
            active_job = self._active_job_locked()
            if active_job is not None:
                raise OptionsScreenerScanConflict(active_job)

            tickers = tuple(
                self.settings_store.get_ticker_list(
                    "cs" if screener == "cs" else "csp_cc"
                )
            )
            filters = self.settings_store.get_filters(screener).model_copy(deep=True)
            job = OptionsScreenerScanJob(
                id=uuid4().hex,
                screener=screener,
                status="active",
                tickers=list(tickers),
                filters=filters,
                total_tickers=len(tickers),
                progress_message=f"0 of {len(tickers)} tickers scanned",
                started_at=utc_now(),
            )
            cancel_event = threading.Event()
            self.jobs[job.id] = job
            self.active_job_id = job.id
            self.latest_job_ids[screener] = job.id
            self.cancel_events[job.id] = cancel_event
            thread = threading.Thread(
                target=self._run_job,
                args=(job.id, tickers, filters, cancel_event),
                daemon=True,
                name=f"options-screener-{job.id}",
            )
            self.threads.add(thread)
            snapshot = job.model_copy(deep=True)

        self._publish(OptionsScreenerScanEvent(type="job_started", job=snapshot))
        thread.start()
        return snapshot

    def cancel(self, job_id: str) -> OptionsScreenerScanJob:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise OptionsScreenerJobNotFound(job_id)
            if job.status != "active":
                raise OptionsScreenerJobNotActive(
                    f"Scan {job_id} is not active."
                )
            self.cancel_events[job_id].set()
            snapshot = job.model_copy(deep=True)
        self._cancel_services()
        return snapshot

    def get_job(self, job_id: str) -> OptionsScreenerScanJob:
        with self.lock:
            self._purge_expired_locked()
            job = self.jobs.get(job_id)
            if job is None:
                raise OptionsScreenerJobNotFound(job_id)
            return job.model_copy(deep=True)

    def state(self) -> OptionsScreenerScanState:
        with self.lock:
            self._purge_expired_locked()
            active_job = self._active_job_locked()
            return OptionsScreenerScanState(
                active_job=(
                    active_job.model_copy(deep=True)
                    if active_job is not None
                    else None
                ),
                latest_jobs={
                    screener: self._job_copy(job_id)
                    for screener, job_id in self.latest_job_ids.items()
                },
                completed_snapshots={
                    screener: (
                        snapshot.model_copy(deep=True)
                        if snapshot is not None
                        else None
                    )
                    for screener, snapshot in self.completed_snapshots.items()
                },
            )

    def completed_snapshot(
        self,
        screener: OptionsScreener,
    ) -> OptionsScreenerCompletedSnapshot | None:
        with self.lock:
            snapshot = self.completed_snapshots[screener]
            return snapshot.model_copy(deep=True) if snapshot is not None else None

    def subscribe(self) -> queue.Queue[OptionsScreenerScanEvent]:
        subscriber: queue.Queue[OptionsScreenerScanEvent] = queue.Queue(
            maxsize=self.subscriber_queue_size
        )
        with self.lock:
            self.subscribers.add(subscriber)
        return subscriber

    def unsubscribe(
        self,
        subscriber: queue.Queue[OptionsScreenerScanEvent],
    ) -> None:
        with self.lock:
            self.subscribers.discard(subscriber)

    def refresh_quote(
        self,
        request: OptionsScreenerQuoteRefreshRequest,
    ) -> OptionsScreenerQuoteRefreshResponse:
        return self.quote_refresh_service.refresh_quote(request)

    def refresh_spread_quote(
        self,
        request: OptionsScreenerSpreadQuoteRefreshRequest,
    ) -> OptionsScreenerSpreadQuoteRefreshResponse:
        return self.spread_quote_refresh_service.refresh_spread_quote(request)

    def shutdown(self) -> None:
        with self.lock:
            cancel_events = list(self.cancel_events.values())
            threads = list(self.threads)
        for cancel_event in cancel_events:
            cancel_event.set()
        self._cancel_services()
        for thread in threads:
            thread.join(timeout=1)

    def _run_job(
        self,
        job_id: str,
        tickers: tuple[str, ...],
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> None:
        try:
            job = self.get_job(job_id)
            self._scan_service(job.screener).prepare_scan(
                job.screener,
                tickers,
                filters,
                cancel_event,
            )
            ticker_queue: queue.Queue[str] = queue.Queue()
            for ticker in tickers:
                ticker_queue.put(ticker)

            with ThreadPoolExecutor(
                max_workers=min(self.max_workers, max(1, len(tickers))),
                thread_name_prefix=f"screener-{job_id}",
            ) as executor:
                futures = [
                    executor.submit(
                        self._worker,
                        job_id,
                        ticker_queue,
                        filters,
                        cancel_event,
                    )
                    for _ in range(min(self.max_workers, len(tickers)))
                ]
                for future in futures:
                    future.result()

            self._finish_job(job_id, cancelled=cancel_event.is_set())
        except Exception as error:
            self._fail_job(job_id, str(error))
        finally:
            with self.lock:
                self.cancel_events.pop(job_id, None)
                self.threads.discard(threading.current_thread())

    def _worker(
        self,
        job_id: str,
        ticker_queue: queue.Queue[str],
        filters: OptionsScreenerFilters | CreditSpreadScreenerFilters,
        cancel_event: threading.Event,
    ) -> None:
        while not cancel_event.is_set():
            try:
                ticker = ticker_queue.get_nowait()
            except queue.Empty:
                return
            try:
                if cancel_event.is_set():
                    return
                with self.lock:
                    job = self.jobs[job_id]
                    screener = job.screener
                result = self._scan_service(screener).scan_ticker(
                    screener,
                    ticker,
                    filters,
                    cancel_event,
                )
                if cancel_event.is_set():
                    return
                self._record_ticker_result(job_id, ticker, result)
            except Exception as error:
                if cancel_event.is_set():
                    return
                self._record_ticker_failure(job_id, ticker, str(error))
            finally:
                ticker_queue.task_done()

    def _record_ticker_result(
        self,
        job_id: str,
        ticker: str,
        result: OptionsScreenerTickerResult,
    ) -> None:
        with self.lock:
            job = self.jobs[job_id]
            if job.status != "active":
                return
            self._record_ticker_progress_locked(job)
            job.excluded_contracts += result.excluded_contracts
            job.warnings.extend(result.warnings)
            job.total_match_count += len(result.candidates)
            self._record_ticker_candidates_locked(job, result)
            self._record_no_match_locked(job, ticker, result)
            snapshot = job.model_copy(deep=True)
        self._publish(OptionsScreenerScanEvent(type="job_updated", job=snapshot))

    def _record_ticker_failure(
        self,
        job_id: str,
        ticker: str,
        message: str,
    ) -> None:
        with self.lock:
            job = self.jobs[job_id]
            if job.status != "active":
                return
            self._record_ticker_progress_locked(job)
            job.failed_tickers += 1
            job.errors.append(f"{ticker}: {message}")
            snapshot = job.model_copy(deep=True)
        self._publish(OptionsScreenerScanEvent(type="job_updated", job=snapshot))

    def _finish_job(self, job_id: str, *, cancelled: bool) -> None:
        with self.lock:
            job = self.jobs[job_id]
            if job.status != "active":
                return
            job.finished_at = utc_now()
            if cancelled:
                job.status = "cancelled"
            else:
                job.status = "completed"
                job.successful_completion_at = job.finished_at
                self.completed_snapshots[job.screener] = (
                    self._completed_snapshot_locked(job)
                )
            self.active_job_id = None
            snapshot = job.model_copy(deep=True)
        self._publish(OptionsScreenerScanEvent(type="job_finished", job=snapshot))

    def _fail_job(self, job_id: str, message: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.status != "active":
                return
            job.status = "failed"
            job.finished_at = utc_now()
            job.errors.append(message)
            self.active_job_id = None
            snapshot = job.model_copy(deep=True)
        self._publish(OptionsScreenerScanEvent(type="job_finished", job=snapshot))

    def _publish(self, event: OptionsScreenerScanEvent) -> None:
        with self.lock:
            for subscriber in self.subscribers:
                if subscriber.full():
                    try:
                        subscriber.get_nowait()
                    except queue.Empty:
                        pass
                subscriber.put_nowait(event)

    def _active_job_locked(self) -> OptionsScreenerScanJob | None:
        if self.active_job_id is None:
            return None
        job = self.jobs.get(self.active_job_id)
        if job is None or job.status != "active":
            self.active_job_id = None
            return None
        return job

    def _job_copy(self, job_id: str | None) -> OptionsScreenerScanJob | None:
        if job_id is None:
            return None
        job = self.jobs.get(job_id)
        return job.model_copy(deep=True) if job is not None else None

    def _record_ticker_progress_locked(
        self,
        job: OptionsScreenerScanJob,
    ) -> None:
        job.completed_tickers += 1
        job.progress_message = (
            f"{job.completed_tickers} of {job.total_tickers} tickers scanned"
        )

    def _record_ticker_candidates_locked(
        self,
        job: OptionsScreenerScanJob,
        result: OptionsScreenerTickerResult,
    ) -> None:
        if not result.candidates:
            return
        job.successful_tickers += 1
        job.candidates = sort_candidates(
            [*job.candidates, *result.candidates]
        )[:500]

    def _record_no_match_locked(
        self,
        job: OptionsScreenerScanJob,
        ticker: str,
        result: OptionsScreenerTickerResult,
    ) -> None:
        if result.candidates:
            return
        job.no_match_tickers += 1
        if any(warning.category == "no_matches" for warning in result.warnings):
            return
        job.warnings.append(
            OptionsScreenerTickerWarning(
                ticker=ticker,
                category="no_matches",
                message="No contracts matched the saved filters.",
            )
        )

    def _completed_snapshot_locked(
        self,
        job: OptionsScreenerScanJob,
    ) -> OptionsScreenerCompletedSnapshot:
        return OptionsScreenerCompletedSnapshot(
            screener=job.screener,
            job_id=job.id,
            total_match_count=job.total_match_count,
            excluded_contracts=job.excluded_contracts,
            candidates=job.candidates,
            errors=job.errors,
            warnings=job.warnings,
            completed_at=job.successful_completion_at,
        )

    def _purge_expired_locked(self) -> None:
        cutoff = datetime.now(UTC) - self.retention
        expired_ids = [
            job_id
            for job_id, job in self.jobs.items()
            if job.status in {"cancelled", "failed"}
            and job.finished_at is not None
            and datetime.fromisoformat(job.finished_at) < cutoff
        ]
        for job_id in expired_ids:
            job = self.jobs.pop(job_id)
            if self.latest_job_ids[job.screener] == job_id:
                self.latest_job_ids[job.screener] = None

    def _scan_service(self, screener: OptionsScreener) -> OptionsScreenerScanService:
        return self.scan_services[screener]

    def _cancel_services(self) -> None:
        seen: set[int] = set()
        for service in self.scan_services.values():
            service_id = id(service)
            if service_id in seen:
                continue
            seen.add(service_id)
            service.cancel()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
