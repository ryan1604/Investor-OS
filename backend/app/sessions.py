from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from app.schemas import RiskSnapshotKind

US_MARKET_TIME_ZONE = ZoneInfo("America/New_York")
US_MARKET_OPEN = time(9, 30)
US_MARKET_CLOSE = time(16, 0)


def weekday_on_or_before(day: date) -> date:
    """Roll weekends back to Friday, leaving weekdays unchanged."""
    while day.weekday() > 4:
        day -= timedelta(days=1)
    return day


def us_session_date(now: datetime) -> date:
    """Return the US trading date for now, rolling weekends back to Friday."""
    return weekday_on_or_before(now.astimezone(US_MARKET_TIME_ZONE).date())


def snapshot_session(now: datetime) -> tuple[date, RiskSnapshotKind]:
    """Key a risk snapshot to a US session: the current one while the market is
    open, otherwise the last completed one. Weekends are handled; holidays are not.
    """
    local = now.astimezone(US_MARKET_TIME_ZONE)
    today = local.date()
    if today.weekday() < 5:
        if US_MARKET_OPEN <= local.time() < US_MARKET_CLOSE:
            return today, "intraday"
        if local.time() >= US_MARKET_CLOSE:
            return today, "post_close"
    return us_session_date(local - timedelta(days=1)), "post_close"
