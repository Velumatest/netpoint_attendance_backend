from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from app.core.config import settings

# Business timezone: schedules, "today" and date filters are interpreted in this zone.
LOCAL_TZ = ZoneInfo(settings.app_timezone)


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def local_today() -> date:
    return local_now().date()


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Start (inclusive) and end (exclusive) of a local calendar day, as aware datetimes."""
    start = datetime.combine(day, time.min, LOCAL_TZ)
    return start, start + timedelta(days=1)
