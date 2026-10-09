from datetime import UTC, datetime, timedelta
import threading
import time

import pytest

from app.options_screeners.manager import (
    OptionsScreenerJobNotFound,
    OptionsScreenerScanConflict,
    OptionsScreenerScanManager,
)
from app.options_screeners.service import OptionsScreenerTickerResult
from app.options_screeners.store import OptionsScreenerSettingsStore
from app.schemas import (
    CashSecuredPutCandidate,
    CoveredCallCandidate,
    CreditSpreadCandidate,
    CreditSpreadScreenerFilters,
    OptionContractIdentity,
    OptionsScreenerFilters,
    OptionsScreenerQuoteRefreshResponse,
)


class FakeScanService:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.active = 0
        self.max_active = 0
        self.requests: list[str] = []
        self.prepared = []
        self.results = {}
        self.failures = {}
        self.prepare_error: Exception | None = None
        self.cancel_calls = 0

    def prepare_scan(self, screener, tickers, filters, cancel_event):
        if self.prepare_error is not None:
            error = self.prepare_error
            self.prepare_error = None
            raise error
        self.prepared.append((screener, tickers, filters.model_copy(deep=True)))

    def scan_ticker(self, screener, ticker, filters, cancel_event):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.requests.append(ticker)
            self.started.set()
        try:
            while not self.release.wait(0.01):
                if cancel_event.is_set():
                    return OptionsScreenerTickerResult()
            if ticker in self.failures:
                raise RuntimeError(self.failures[ticker])
            return self.results.get(ticker, OptionsScreenerTickerResult())
        finally:
            with self.lock:
                self.active -= 1

    def cancel(self):
        self.cancel_calls += 1
        self.release.set()

    def refresh_quote(self, request):
        return OptionsScreenerQuoteRefreshResponse(
            **request.model_dump(),
            bid=1,
            ask=1.2,
            midpoint=1.1,
            delta=-0.2,
            refreshed_at="2026-06-14T00:00:00+00:00",
        )


def scan_manager(store, service, **kwargs):
    return OptionsScreenerScanManager(
        store,
        {"csp": service, "cc": service, "cs": service},
        service,
        service,
        **kwargs,
    )


def test_scan_captures_settings_and_processes_all_tickers_with_bounded_work(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL", "MSFT", "NVDA", "AMD", "META"])
    store.save_filters("csp", OptionsScreenerFilters(minimum_dte=10))
    service = FakeScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    manager = scan_manager(store, service, max_workers=2)

    job = manager.start("csp")
    store.replace_ticker_list("csp_cc", ["CHANGED"])
    store.save_filters("csp", OptionsScreenerFilters(minimum_dte=20))
    completed = wait_for_terminal(manager, job.id)

    assert completed.status == "completed"
    assert completed.tickers == ["AAPL", "MSFT", "NVDA", "AMD", "META"]
    assert completed.filters.minimum_dte == 10
    assert completed.completed_tickers == 5
    assert completed.progress_message == "5 of 5 tickers scanned"
    assert completed.successful_tickers == 1
    assert completed.no_match_tickers == 4
    assert set(service.requests) == {"AAPL", "MSFT", "NVDA", "AMD", "META"}
    assert service.max_active <= 2
    assert service.prepared[0][1] == ("AAPL", "MSFT", "NVDA", "AMD", "META")


def test_only_one_scan_runs_globally(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL"])
    service = FakeScanService()
    service.release.clear()
    manager = scan_manager(store, service)

    active = manager.start("csp")
    assert service.started.wait(1)

    with pytest.raises(OptionsScreenerScanConflict) as error:
        manager.start("cc")

    assert error.value.job.id == active.id
    assert error.value.job.screener == "csp"
    manager.cancel(active.id)
    wait_for_terminal(manager, active.id)


def test_all_screeners_share_job_limit_but_keep_tickers_filters_and_snapshots_isolated(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL"])
    store.replace_ticker_list("cs", ["TSLA"])
    store.save_filters("csp", OptionsScreenerFilters(minimum_dte=10))
    store.save_filters("cc", OptionsScreenerFilters(minimum_dte=20))
    store.save_filters(
        "cs",
        CreditSpreadScreenerFilters(
            minimum_dte=30,
            strategy_types=["put_credit_spread"],
            spread_widths=[5],
        ),
    )
    service = FakeScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    manager = scan_manager(store, service)

    csp = wait_for_terminal(manager, manager.start("csp").id)
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[cc_candidate("AAPL")]
    )
    cc = wait_for_terminal(manager, manager.start("cc").id)
    service.results["TSLA"] = OptionsScreenerTickerResult(
        candidates=[cs_candidate("TSLA")]
    )
    cs = wait_for_terminal(manager, manager.start("cs").id)
    state = manager.state()

    assert [prepared[0] for prepared in service.prepared] == ["csp", "cc", "cs"]
    assert service.prepared[0][1] == ("AAPL",)
    assert service.prepared[1][1] == ("AAPL",)
    assert service.prepared[2][1] == ("TSLA",)
    assert service.prepared[0][2].minimum_dte == 10
    assert service.prepared[1][2].minimum_dte == 20
    assert service.prepared[2][2].minimum_dte == 30
    assert csp.candidates[0].strategy == "csp"
    assert cc.candidates[0].strategy == "cc"
    assert cs.candidates[0].strategy == "put_credit_spread"
    assert state.active_job is None
    assert state.completed_snapshots["csp"].job_id == csp.id
    assert state.completed_snapshots["cc"].job_id == cc.id
    assert state.completed_snapshots["cs"].job_id == cs.id


def test_ticker_failures_count_as_terminal_without_failing_job(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL", "FAIL", "EMPTY"])
    service = FakeScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    service.failures["FAIL"] = "market unavailable"
    manager = scan_manager(store, service)

    completed = wait_for_terminal(manager, manager.start("csp").id)

    assert completed.status == "completed"
    assert completed.completed_tickers == 3
    assert completed.successful_tickers == 1
    assert completed.no_match_tickers == 1
    assert completed.failed_tickers == 1
    assert completed.errors == ["FAIL: market unavailable"]


def test_cancelled_and_fatal_scans_preserve_previous_snapshot(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL", "FAIL"])
    service = FakeScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    service.failures["FAIL"] = "market unavailable"
    manager = scan_manager(store, service)

    first = wait_for_terminal(manager, manager.start("csp").id)
    previous = manager.completed_snapshot("csp")
    assert previous is not None
    assert previous.job_id == first.id
    assert previous.errors == ["FAIL: market unavailable"]

    service.release.clear()
    cancelled_job = manager.start("csp")
    assert service.started.wait(1)
    manager.cancel(cancelled_job.id)
    cancelled = wait_for_terminal(manager, cancelled_job.id)

    assert cancelled.status == "cancelled"
    assert manager.completed_snapshot("csp") == previous

    service.prepare_error = RuntimeError("fatal setup")
    failed = wait_for_terminal(manager, manager.start("csp").id)

    assert failed.status == "failed"
    assert failed.errors == ["fatal setup"]
    recovered = manager.state().completed_snapshots["csp"]
    assert recovered == previous
    assert recovered.errors == ["FAIL: market unavailable"]


def test_concurrent_publishers_replace_events_in_full_subscriber_queue(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    manager = scan_manager(
        store,
        FakeScanService(),
        subscriber_queue_size=1,
    )
    subscriber = manager.subscribe()
    subscriber.put_nowait(scan_event("initial"))
    start = threading.Barrier(9)
    errors: list[Exception] = []

    def publish(index: int) -> None:
        start.wait()
        try:
            manager._publish(scan_event(f"job-{index}"))
        except Exception as error:
            errors.append(error)

    threads = [
        threading.Thread(target=publish, args=(index,))
        for index in range(8)
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=1)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    assert subscriber.qsize() == 1
    assert subscriber.get_nowait().job.id.startswith("job-")


def test_successful_zero_match_scan_replaces_previous_snapshot(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL"])
    service = FakeScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    manager = scan_manager(store, service)

    first = wait_for_terminal(manager, manager.start("csp").id)
    service.results.clear()
    second = wait_for_terminal(manager, manager.start("csp").id)
    snapshot = manager.completed_snapshot("csp")

    assert first.candidates
    assert second.status == "completed"
    assert second.candidates == []
    assert snapshot is not None
    assert snapshot.job_id == second.id
    assert snapshot.candidates == []
    assert snapshot.completed_at == second.successful_completion_at


def test_cancelled_and_failed_jobs_expire_but_active_jobs_do_not(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL"])
    service = FakeScanService()
    manager = scan_manager(store, service, retention_minutes=30)
    service.prepare_error = RuntimeError("fatal")
    failed = wait_for_terminal(manager, manager.start("csp").id)
    with manager.lock:
        manager.jobs[failed.id].finished_at = (
            datetime.now(UTC) - timedelta(minutes=31)
        ).isoformat()

    with pytest.raises(OptionsScreenerJobNotFound):
        manager.get_job(failed.id)

    service.release.clear()
    active = manager.start("csp")
    assert service.started.wait(1)
    with manager.lock:
        manager.jobs[active.id].started_at = (
            datetime.now(UTC) - timedelta(hours=2)
        ).isoformat()
    assert manager.get_job(active.id).status == "active"
    manager.cancel(active.id)


def test_new_manager_has_no_jobs_or_completed_snapshots(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL"])
    service = FakeScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[candidate("AAPL")]
    )
    manager = scan_manager(store, service)
    wait_for_terminal(manager, manager.start("csp").id)

    restarted = scan_manager(store, FakeScanService())
    state = restarted.state()

    assert state.active_job is None
    assert all(job is None for job in state.latest_jobs.values())
    assert all(snapshot is None for snapshot in state.completed_snapshots.values())


def test_completed_scan_keeps_total_matches_and_global_top_500(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    store.replace_ticker_list("csp_cc", ["AAPL", "MSFT"])
    service = FakeScanService()
    service.results["AAPL"] = OptionsScreenerTickerResult(
        candidates=[
            candidate("AAPL").model_copy(
                update={"annualized_return": float(index)}
            )
            for index in range(300)
        ]
    )
    service.results["MSFT"] = OptionsScreenerTickerResult(
        candidates=[
            candidate("MSFT").model_copy(
                update={"annualized_return": float(index) + 0.5}
            )
            for index in range(300)
        ]
    )
    manager = scan_manager(store, service)

    completed = wait_for_terminal(manager, manager.start("csp").id)
    snapshot = manager.completed_snapshot("csp")

    assert completed.total_match_count == 600
    assert len(completed.candidates) == 500
    assert completed.candidates[0].annualized_return == 299.5
    assert completed.candidates[-1].annualized_return == 50
    assert snapshot is not None
    assert snapshot.total_match_count == 600
    assert len(snapshot.candidates) == 500


def test_large_deterministic_ticker_universe_stays_within_worker_bound(tmp_path):
    store = OptionsScreenerSettingsStore(tmp_path / "settings.sqlite3")
    tickers = [f"T{index:03d}" for index in range(120)]
    store.replace_ticker_list("csp_cc", tickers)
    service = FakeScanService()
    manager = scan_manager(store, service, max_workers=4)

    completed = wait_for_terminal(manager, manager.start("csp").id)

    assert completed.status == "completed"
    assert completed.completed_tickers == 120
    assert sorted(service.requests) == tickers
    assert service.max_active <= 4


def wait_for_terminal(manager, job_id, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get_job(job_id)
        if job.status != "active":
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not finish.")


def candidate(ticker):
    return CashSecuredPutCandidate(
        ticker=ticker,
        annualized_return=20,
        stock_price=110,
        strike=100,
        expiration="2026-07-17",
        dte=30,
        delta=-0.2,
        bid=1,
        ask=1.2,
        discount_percentage=9.09,
        contract=OptionContractIdentity(
            con_id=123,
            local_symbol=f"{ticker} PUT",
        ),
    )


def cc_candidate(ticker):
    return CoveredCallCandidate(
        ticker=ticker,
        annualized_return=20,
        stock_price=100,
        strike=110,
        expiration="2026-07-17",
        dte=30,
        delta=0.2,
        bid=1,
        ask=1.2,
        gain_percentage=10,
        contract=OptionContractIdentity(
            con_id=456,
            local_symbol=f"{ticker} CALL",
        ),
    )


def cs_candidate(ticker):
    return CreditSpreadCandidate(
        strategy="put_credit_spread",
        ticker=ticker,
        annualized_return=40,
        stock_price=100,
        short_strike=95,
        long_strike=90,
        expiration="2026-07-17",
        dte=30,
        short_delta=-0.2,
        net_bid=1,
        net_ask=1.2,
        distance_percentage=5,
        short_contract=OptionContractIdentity(
            con_id=789,
            local_symbol=f"{ticker} SHORT PUT",
        ),
        long_contract=OptionContractIdentity(
            con_id=790,
            local_symbol=f"{ticker} LONG PUT",
        ),
    )


def scan_event(job_id):
    from app.schemas import OptionsScreenerScanEvent, OptionsScreenerScanJob

    return OptionsScreenerScanEvent(
        type="job_updated",
        job=OptionsScreenerScanJob(
            id=job_id,
            screener="csp",
            status="active",
            tickers=[],
            filters=OptionsScreenerFilters(),
            total_tickers=0,
            progress_message="",
            started_at="2026-06-15T00:00:00+00:00",
        ),
    )
