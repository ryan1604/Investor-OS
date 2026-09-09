import asyncio
import logging
from datetime import date

import httpx
import pytest
from pydantic import SecretStr
from fastapi.testclient import TestClient
from conftest import make_api

from app.portfolio.flex import FlexClient, FlexError, parse_report, xml_root
from app.portfolio.nav_store import DailyNavStore
from app.portfolio.nav_sync import NavSyncService


def report(accounts=("DU1", "DU2"), days=("20260901", "20260902"), first="20260901", last="20260902"):
    statements = "".join(
        f'<FlexStatement accountId="{account}" fromDate="{first}" toDate="{last}">'
        f'<AccountInformation accountId="{account}" currency="USD"/><EquitySummaryInBase>'
        + "".join(f'<EquitySummaryByReportDateInBase accountId="{account}" reportDate="{day}" total="123.456789"/>' for day in days)
        + '</EquitySummaryInBase></FlexStatement>' for account in accounts
    )
    return f'<FlexQueryResponse type="AF"><FlexStatements>{statements}</FlexStatements></FlexQueryResponse>'.encode()


def test_client_polls_and_passes_dates_without_logging_token(caplog):
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, content=b'<FlexStatementResponse><Status>Success</Status><ReferenceCode>ref</ReferenceCode><url>https://evil.test</url></FlexStatementResponse>')
        if len(calls) == 2:
            return httpx.Response(200, content=b'<FlexStatementResponse><ErrorCode>1019</ErrorCode></FlexStatementResponse>')
        return httpx.Response(200, content=report())
    async def run():
        client = FlexClient(SecretStr("test-secret"), "123", transport=httpx.MockTransport(handle), pace_seconds=0)
        try:
            return await client.fetch(date(2026, 9, 1), date(2026, 9, 2))
        finally:
            await client.aclose()
    with caplog.at_level(logging.DEBUG):
        values = asyncio.run(run())
    assert len(values) == 4
    assert calls[0].url.params["fd"] == "20260901"
    assert calls[0].url.params["td"] == "20260902"
    assert calls[1].url.params["q"] == "ref"
    assert all(r.url.host == "ndcdyn.interactivebrokers.com" for r in calls)
    assert "test-secret" not in caplog.text


@pytest.mark.parametrize("code,expected", [("1012", "credentials"), ("1015", "credentials"), ("1019", "unavailable"), ("1020", "invalid_report")])
def test_safe_errors_and_bounded_retry(code, expected):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=f'<Response><ErrorCode>{code}</ErrorCode><ErrorMessage>secret</ErrorMessage></Response>'.encode())
    async def run():
        client = FlexClient(SecretStr("secret"), "123", transport=httpx.MockTransport(handle), pace_seconds=0, attempts=2)
        try:
            with pytest.raises(FlexError) as failure:
                await client.fetch()
            assert str(failure.value) == expected
        finally:
            await client.aclose()
    asyncio.run(run())
    assert len(calls) == (2 if code == "1019" else 1)


def test_network_timeout_is_safe_and_retried():
    def handle(request):
        raise httpx.ReadTimeout("secret URL", request=request)
    async def run():
        client = FlexClient(SecretStr("secret"), "123", transport=httpx.MockTransport(handle), pace_seconds=0, attempts=2)
        try:
            with pytest.raises(FlexError, match="unavailable"):
                await client.fetch()
        finally:
            await client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("content", [b'broken', b'<!DOCTYPE x><x/>', b'<FlexQueryResponse type="AF"/>',
    report().replace(b'currency="USD"', b'currency=""'),
    report().replace(b'total="123.456789"', b'total="NaN"'),
    report().replace(b'<AccountInformation accountId="DU1"', b'<AccountInformation accountId="DU3"'),
    report().replace(b'20260901', b'20260230'),
])
def test_invalid_reports_rejected(content):
    with pytest.raises(FlexError, match="invalid_report"):
        parse_report(xml_root(content))


def test_ignored_date_override_rejected():
    with pytest.raises(FlexError):
        parse_report(xml_root(report()), date(2026, 8, 1), date(2026, 8, 2))
    with pytest.raises(FlexError):
        parse_report(xml_root(report()), date(2026, 8, 25), date(2026, 9, 2))


class FakeFlex:
    def __init__(self, values):
        self.values = values
        self.calls = []
        self.closed = False
    async def fetch(self, start=None, end=None):
        self.calls.append((start, end))
        if isinstance(self.values, Exception):
            raise self.values
        return self.values
    async def aclose(self):
        self.closed = True


def test_bootstrap_catchup_restart_and_failure_preserves_history(tmp_path):
    async def run():
        store = DailyNavStore(tmp_path / "nav.sqlite3")
        client = FakeFlex(parse_report(xml_root(report())))
        service = NavSyncService(store, client, clock=lambda: date(2026, 9, 8))
        await service.sync_once()
        assert len(store.history("DU1").rows) == 1
        assert store.history("DU1").latest_report_date == "2026-09-02"
        restarted = DailyNavStore(store.database_path)
        client.values = parse_report(xml_root(report(days=("20260902", "20260903", "20260904", "20260907"), last="20260907")))
        service = NavSyncService(restarted, client, clock=lambda: date(2026, 9, 8))
        await service.sync_once()
        assert client.calls[-1] == (date(2026, 8, 26), date(2026, 9, 7))
        assert len(restarted.history("DU1").rows) == 4
        before = restarted.history("DU1")
        await service.sync_once()
        assert restarted.history("DU1").rows == before.rows
        client.values = FlexError("credentials")
        await service.sync_once()
        assert restarted.history("DU1").rows == before.rows
        assert restarted.history("DU1").sync.error
        assert restarted.history("DU1").sync.last_successful_sync
    asyncio.run(run())


def test_unexpected_account_rejected_atomically(tmp_path):
    async def run():
        store = DailyNavStore(tmp_path / "nav.sqlite3")
        store.upsert_values(parse_report(xml_root(report())))
        before = store.history("DU1").rows
        service = NavSyncService(store, FakeFlex(parse_report(xml_root(report(accounts=("DU1", "DU3"))))), clock=lambda: date(2026, 9, 8))
        await service.sync_once()
        assert store.list_accounts() == ["DU1", "DU2"]
        assert store.history("DU1").rows == before
        assert service.error == "The IBKR report could not be validated."
    asyncio.run(run())


def test_lifecycle_cancellation_and_nonoverlap(tmp_path):
    async def run():
        entered = asyncio.Event()
        class WaitingFlex(FakeFlex):
            async def fetch(self, start=None, end=None):
                self.calls.append((start, end))
                entered.set()
                await asyncio.Event().wait()
        client = WaitingFlex([])
        service = NavSyncService(DailyNavStore(tmp_path / "nav.sqlite3"), client)
        service.start()
        service.start()
        await asyncio.wait_for(entered.wait(), timeout=1)
        await service.sync_once()
        assert len(client.calls) == 1
        await asyncio.wait_for(service.stop(), timeout=1)
        assert client.closed and not service.syncing and service.task is None
    asyncio.run(run())


def test_periodic_retry_after_failure(tmp_path):
    async def run():
        retried = asyncio.Event()
        class RecoveringFlex(FakeFlex):
            async def fetch(self, start=None, end=None):
                self.calls.append((start, end))
                if len(self.calls) == 1:
                    raise FlexError("unavailable")
                retried.set()
                return self.values
        client = RecoveringFlex(parse_report(xml_root(report())))
        service = NavSyncService(DailyNavStore(tmp_path / "nav.sqlite3"), client,
                                 interval_seconds=0.01, clock=lambda: date(2026, 9, 8))
        service.start()
        await asyncio.wait_for(retried.wait(), timeout=1)
        for _ in range(100):
            if not service.syncing:
                break
            await asyncio.sleep(0.001)
        await service.stop()
        assert service.store.list_accounts() == ["DU1", "DU2"]
        assert service.error is None
    asyncio.run(run())


def test_long_catchup_is_bounded_and_weekends_are_not_requested_individually(tmp_path):
    async def run():
        store = DailyNavStore(tmp_path / "nav.sqlite3")
        store.upsert_values(parse_report(xml_root(report())))
        client = FakeFlex(FlexError("unavailable"))
        service = NavSyncService(store, client, clock=lambda: date(2027, 1, 3))
        await service.sync_once()
        first, last = client.calls[0]
        assert (last - first).days == 30
        assert len(client.calls) == 1
    asyncio.run(run())


def test_cancellation_interrupts_http_wait():
    async def run():
        entered = asyncio.Event()
        async def handle(request):
            entered.set()
            await asyncio.Event().wait()
        client = FlexClient(SecretStr("secret"), "123", transport=httpx.MockTransport(handle), pace_seconds=0)
        task = asyncio.create_task(client.fetch())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        await client.aclose()
    asyncio.run(run())


def test_api_sync_states_without_live_tws(tmp_path):
    api = make_api(portfolio_chart_values_database_path=tmp_path / "nav.sqlite3")
    with TestClient(api) as client:
        api.state.settings.ibkr_flex_token = SecretStr("fake-token")
        api.state.settings.ibkr_flex_query_id = "123"
        service = api.state.portfolio_nav_sync
        assert client.get("/portfolio/nav?account=DU1").json()["sync"]["state"] == "pending"
        service.syncing = True
        assert client.get("/portfolio/nav?account=DU1").json()["sync"]["state"] == "syncing"
        service.syncing = False
        service.error = "IBKR reporting is temporarily unavailable."
        assert client.get("/portfolio/nav?account=DU1").json()["sync"]["state"] == "failed"
        service.error = None
        api.state.portfolio_nav_store.upsert_values(parse_report(xml_root(report())))
        assert client.get("/portfolio/nav?account=DU1").json()["sync"]["state"] in {"current", "stale"}


def test_store_releases_sqlite_handles(tmp_path):
    store = DailyNavStore(tmp_path / "nav.sqlite3")
    store.upsert_values(parse_report(xml_root(report())))
    store.record_sync("DU1")
    store.history("DU1")
    store.list_accounts()
    store.database_path.unlink()
    assert not store.database_path.exists()
