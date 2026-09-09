import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx
from pydantic import SecretStr

from app.portfolio.nav_store import DailyNav, SyncError

BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
RETRY_CODES = {"1001", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1018", "1019", "1021"}


class FlexError(Exception):
    def __init__(self, code: SyncError):
        self.code = code
        super().__init__(code)


class _HideFlexRequests(logging.Filter):
    def filter(self, record):
        # HTTPX logs complete URLs, including Flex tokens. Never emit those records.
        return "FlexWebService" not in record.getMessage()


def xml_root(content: bytes) -> ET.Element:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise FlexError("invalid_report")
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        raise FlexError("invalid_report") from None


def report_date(raw: str) -> date:
    if not re.fullmatch(r"[0-9]{8}", raw):
        raise ValueError("Invalid report date")
    return datetime.strptime(raw, "%Y%m%d").date()


def parse_report(root: ET.Element, start: date | None = None, end: date | None = None) -> list[DailyNav]:
    try:
        if root.tag != "FlexQueryResponse" or root.get("type") != "AF":
            raise ValueError("Invalid report")
        statements = root.findall("./FlexStatements/FlexStatement")
        if not statements:
            raise ValueError("Empty report")
        values = {}
        ranges = {}
        for statement in statements:
            account = statement.attrib["accountId"]
            info = statement.findall("AccountInformation")
            if len(info) != 1 or info[0].get("accountId") != account:
                raise ValueError("Account mismatch")
            first = report_date(statement.attrib["fromDate"])
            last = report_date(statement.attrib["toDate"])
            if first > last or (start and first < start) or (end and last > end):
                raise ValueError("Unexpected report range")
            ranges.setdefault(account, []).append((first, last))
            entries = statement.findall("./EquitySummaryInBase/EquitySummaryByReportDateInBase")
            if not entries:
                raise ValueError("Missing NAV")
            for entry in entries:
                day = report_date(entry.attrib["reportDate"])
                if entry.get("accountId") != account or day > last:
                    raise ValueError("Unexpected NAV identity/date")
                value = DailyNav(account=account, report_date=day.isoformat(),
                                 nav=entry.attrib["total"], currency=info[0].attrib["currency"], source="flex")
                key = (value.account, value.report_date)
                if key in values and values[key] != value:
                    raise ValueError("Conflicting NAV")
                values[key] = value
        if start and end and any(
            min(first for first, _ in periods) != start
            or max(last for _, last in periods) != end
            for periods in ranges.values()
        ):
            raise ValueError("Requested range was not honored")
        return sorted(values.values(), key=lambda row: (row.account, row.report_date))
    except (ValueError, KeyError):
        raise FlexError("invalid_report") from None


class FlexClient:
    def __init__(self, token: SecretStr, query_id: str, *, transport=None,
                 pace_seconds: float = 6.1, attempts: int = 8):
        self.token = token
        self.query_id = query_id
        self.pace_seconds = pace_seconds
        self.attempts = attempts
        self._last_request = 0.0
        self._filter = _HideFlexRequests()
        logging.getLogger("httpx").addFilter(self._filter)
        self.http = httpx.AsyncClient(timeout=20, transport=transport, follow_redirects=False)

    async def aclose(self):
        await self.http.aclose()
        logging.getLogger("httpx").removeFilter(self._filter)

    async def _request(self, endpoint: str, params: dict[str, str]) -> ET.Element:
        for _ in range(self.attempts):
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0, self._last_request + self.pace_seconds - loop.time()))
            self._last_request = loop.time()
            try:
                response = await self.http.get(f"{BASE_URL}/{endpoint}", params={
                    **params, "t": self.token.get_secret_value(), "v": "3",
                })
                if response.status_code in (401, 403):
                    raise FlexError("credentials")
                if response.status_code == 429 or response.status_code >= 500:
                    continue
                if response.status_code != 200:
                    raise FlexError("unavailable")
                root = xml_root(response.content)
            except httpx.HTTPError:
                continue
            code = root.findtext("ErrorCode")
            if code in RETRY_CODES:
                continue
            if code:
                raise FlexError("credentials" if code in {"1011", "1012", "1013", "1014", "1015", "1016"} else "invalid_report")
            return root
        raise FlexError("unavailable")

    async def fetch(self, start: date | None = None, end: date | None = None) -> list[DailyNav]:
        if (start is None) != (end is None) or (start and end and start > end):
            raise FlexError("invalid_report")
        params = {"q": self.query_id}
        if start and end:
            params.update(fd=start.strftime("%Y%m%d"), td=end.strftime("%Y%m%d"))
        try:
            async with asyncio.timeout(120):
                root = await self._request("SendRequest", params)
                reference = root.findtext("ReferenceCode")
                if root.findtext("Status") != "Success" or not reference:
                    raise FlexError("invalid_report")
                report = await self._request("GetStatement", {"q": reference})
                return parse_report(report, start, end)
        except TimeoutError:
            raise FlexError("unavailable") from None
