from contextlib import nullcontext
from datetime import date

import anyio
import httpx
import pytest

from app.earnings_watch.provider import (
    ALPHA_VANTAGE_EARNINGS_CALENDAR_URL,
    AlphaVantageEarningsCalendarClient,
    EarningsCalendarProviderError,
    parse_earnings_calendar_csv,
)
from app.main import AppOverrides, create_app
from tests.conftest import (
    FakePortfolioClient,
    FakeUnavailableOptionsClient,
    make_test_settings,
)


def test_parser_selects_nearest_future_date_and_preserves_symbol_punctuation():
    parsed = parse_earnings_calendar_csv(
        "\n".join(
            [
                "symbol,name,reportDate",
                "INFO,Information Services,2026-07-31",
                "BRK.B,Berkshire,2026-08-01",
                "BRK.B,Berkshire,2026-07-30",
                "RDS-A,Shell,2026-07-29",
                "AAPL,Apple,2026-06-17",
                "bad row,Nope,not-a-date",
            ]
        ),
        today=date(2026, 6, 18),
    )

    assert parsed == {
        "BRK.B": date(2026, 7, 30),
        "INFO": date(2026, 7, 31),
        "RDS-A": date(2026, 7, 29),
    }


@pytest.mark.parametrize(
    "body",
    [
        '{"Note":"Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."}',
        "Information: premium endpoint entitlement required",
        '{"Error Message":"Invalid API call."}',
        "symbol,name\nAAPL,Apple",
        "symbol,name,reportDate\nAAPL,Apple,2026-01-01",
    ],
)
def test_parser_rejects_throttled_invalid_and_empty_responses(body):
    with pytest.raises(EarningsCalendarProviderError):
        parse_earnings_calendar_csv(body, today=date(2026, 6, 18))


@pytest.mark.parametrize(
    ("body", "category"),
    [
        (
            '{"Note":"Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."}',
            "rate_limited",
        ),
        ('{"Error Message":"Invalid API call."}', "invalid_response"),
        ("", "invalid_response"),
    ],
)
def test_parser_classifies_json_errors_rate_limits_and_empty_responses(
    body,
    category,
):
    with pytest.raises(EarningsCalendarProviderError) as error:
        parse_earnings_calendar_csv(body, today=date(2026, 6, 18))

    assert error.value.category == category


def test_alpha_vantage_client_requests_complete_csv_without_symbol_or_datatype():
    anyio.run(assert_alpha_vantage_client_requests_complete_csv_without_symbol_or_datatype)


async def assert_alpha_vantage_client_requests_complete_csv_without_symbol_or_datatype():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text="symbol,name,reportDate\nAAPL,Apple,2026-07-30\n",
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AlphaVantageEarningsCalendarClient(
            "secret",
            client=http_client,
        )
        result = await client.fetch_calendar(today=date(2026, 6, 18))

    request = requests[0]
    assert str(request.url).startswith(ALPHA_VANTAGE_EARNINGS_CALENDAR_URL)
    assert dict(request.url.params) == {
        "function": "EARNINGS_CALENDAR",
        "horizon": "3month",
        "apikey": "secret",
    }
    assert result == {"AAPL": date(2026, 7, 30)}


def test_alpha_vantage_client_follows_redirects_and_maps_timeout():
    anyio.run(assert_alpha_vantage_client_follows_redirects_and_maps_timeout)


async def assert_alpha_vantage_client_follows_redirects_and_maps_timeout():
    def redirect_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/query":
            return httpx.Response(302, headers={"Location": "/redirected"})
        return httpx.Response(200, text="symbol,name,reportDate\nMSFT,Microsoft,2026-08-01\n")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(redirect_handler),
        base_url="https://www.alphavantage.co",
        follow_redirects=True,
    ) as http_client:
        client = AlphaVantageEarningsCalendarClient("secret", client=http_client)
        result = await client.fetch_calendar(today=date(2026, 6, 18))

    assert result == {"MSFT": date(2026, 8, 1)}

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(timeout_handler),
    ) as http_client:
        client = AlphaVantageEarningsCalendarClient("secret", client=http_client)
        with pytest.raises(EarningsCalendarProviderError) as error:
            await client.fetch_calendar(today=date(2026, 6, 18))

    assert error.value.category == "timeout"


def test_alpha_vantage_client_maps_missing_key_and_network_errors():
    anyio.run(assert_alpha_vantage_client_maps_missing_key_and_network_errors)


async def assert_alpha_vantage_client_maps_missing_key_and_network_errors():
    missing_key_client = AlphaVantageEarningsCalendarClient(None)
    with pytest.raises(EarningsCalendarProviderError) as missing_key:
        await missing_key_client.fetch_calendar(today=date(2026, 6, 18))
    await missing_key_client.aclose()
    assert missing_key.value.category == "not_configured"

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AlphaVantageEarningsCalendarClient("secret", client=http_client)
        with pytest.raises(EarningsCalendarProviderError) as network:
            await client.fetch_calendar(today=date(2026, 6, 18))

    assert network.value.category == "network"


def test_app_lifespan_closes_earnings_calendar_provider(tmp_path, monkeypatch):
    for fail in (False, True):
        provider = ClosingProvider()
        portfolio = FakePortfolioClient()
        options = FakeUnavailableOptionsClient()
        api = create_app(
            make_test_settings(
                tmp_path,
                earnings_watch_database_path=tmp_path / "earnings-watch.sqlite3",
            ),
            AppOverrides(
                client=portfolio,
                options_client=options,
                earnings_calendar_provider=provider,
            ),
        )
        cleanup = []

        def track_async(label, original):
            async def stop():
                cleanup.append(label)
                await original()
            return stop

        def track_sync(label, original):
            def stop():
                cleanup.append(label)
                original()
            return stop

        expectation = pytest.raises(RuntimeError, match="Lifespan test failure") if fail else nullcontext()
        async def run_lifespan():
            async with api.router.lifespan_context(api):
                assert provider.closed is False
                for label, service, method in [
                    ("nav", api.state.portfolio_nav_sync, "stop"),
                    ("portfolio", api.state.portfolio_refresh_service, "stop"),
                    ("earnings", api.state.earnings_watch_service, "stop"),
                    ("provider", provider, "aclose"),
                ]:
                    monkeypatch.setattr(service, method, track_async(label, getattr(service, method)))
                for label, service, method in [
                    ("scanner", api.state.options_screener_scan_manager, "shutdown"),
                    ("options", options, "shutdown"),
                    ("client", portfolio, "stop"),
                ]:
                    monkeypatch.setattr(service, method, track_sync(label, getattr(service, method)))
                if fail:
                    raise RuntimeError("Lifespan test failure")

        with expectation:
            anyio.run(run_lifespan)

        assert provider.closed is True
        assert options.stopped is True
        assert portfolio.stopped is True
        assert api.state.portfolio_refresh_service.task is None
        assert cleanup == ["nav", "portfolio", "scanner", "options", "earnings", "provider", "client"]


class ClosingProvider:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True
