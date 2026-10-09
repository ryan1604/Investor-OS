import csv
import io
import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol

import httpx

from app.sessions import US_MARKET_TIME_ZONE as NEW_YORK
from app.tickers import require_ticker

ALPHA_VANTAGE_EARNINGS_CALENDAR_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_HORIZON = "3month"
RATE_LIMIT_MARKERS = (
    "rate limit",
    "standard api rate limit",
    "frequency",
    "premium",
    "entitlement",
    "thank you for using alpha vantage",
)
ERROR_MARKERS = ("error message", "invalid api call", "information", "note")


class EarningsCalendarProvider(Protocol):
    async def fetch_calendar(
        self,
        *,
        today: date | None = None,
    ) -> dict[str, date]: ...


class EarningsCalendarProviderError(Exception):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class AlphaVantageEarningsCalendarClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            max_redirects=3,
            headers={"User-Agent": "Investor-OS/0.1"},
        )

    async def fetch_calendar(
        self,
        *,
        today: date | None = None,
    ) -> dict[str, date]:
        if not self.api_key:
            raise EarningsCalendarProviderError("not_configured")

        try:
            response = await self._client.get(
                ALPHA_VANTAGE_EARNINGS_CALENDAR_URL,
                params={
                    "function": "EARNINGS_CALENDAR",
                    "horizon": ALPHA_VANTAGE_HORIZON,
                    "apikey": self.api_key,
                },
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise EarningsCalendarProviderError("timeout") from error
        except httpx.HTTPError as error:
            raise EarningsCalendarProviderError("network") from error

        return parse_earnings_calendar_csv(
            response.text,
            today=today or datetime.now(NEW_YORK).date(),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def parse_earnings_calendar_csv(
    text: str,
    *,
    today: date,
) -> dict[str, date]:
    reject_provider_error_text(text)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise EarningsCalendarProviderError("invalid_response")

    headers = {header.strip() for header in reader.fieldnames if header}
    if "symbol" not in headers or "reportDate" not in headers:
        raise EarningsCalendarProviderError("invalid_response")

    dates_by_symbol: dict[str, date] = {}
    for row in reader:
        symbol = normalize_provider_symbol(row.get("symbol"))
        report_date = parse_report_date(row.get("reportDate"))
        if symbol is None or report_date is None or report_date < today:
            continue
        current = dates_by_symbol.get(symbol)
        if current is None or report_date < current:
            dates_by_symbol[symbol] = report_date

    if not dates_by_symbol:
        raise EarningsCalendarProviderError("invalid_response")
    return dates_by_symbol


def reject_provider_error_text(text: str) -> None:
    normalized = text.strip()
    if not normalized:
        raise EarningsCalendarProviderError("invalid_response")

    lower_text = normalized.lower()
    if normalized.startswith("{"):
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError as error:
            raise EarningsCalendarProviderError("invalid_response") from error
        if isinstance(payload, Mapping):
            lower_keys = " ".join(str(key).lower() for key in payload)
            lower_values = " ".join(str(value).lower() for value in payload.values())
            lower_text = f"{lower_keys} {lower_values}"
    else:
        first_line = normalized.splitlines()[0].lower()
        if "," in first_line and "symbol" in first_line and "reportdate" in first_line:
            return

    if any(marker in lower_text for marker in RATE_LIMIT_MARKERS):
        raise EarningsCalendarProviderError("rate_limited")
    if any(marker in lower_text for marker in ERROR_MARKERS):
        raise EarningsCalendarProviderError("invalid_response")


def normalize_provider_symbol(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return require_ticker(value)
    except ValueError:
        return None


def parse_report_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None
