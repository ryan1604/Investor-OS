from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas import RiskSnapshotKind

US_MARKET_TIME_ZONE = ZoneInfo("America/New_York")
US_MARKET_OPEN = time(9, 30)
US_MARKET_CLOSE = time(16, 0)


def us_session_date(now: datetime) -> date:
    """Return the US trading date for now, rolling weekends back to Friday."""
    session = now.astimezone(US_MARKET_TIME_ZONE).date()
    while session.weekday() > 4:
        session -= timedelta(days=1)
    return session


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
