from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Stores datetimes as naive UTC in MySQL DATETIME columns and returns them as
    timezone-aware UTC, so API responses carry an explicit "+00:00" offset.

    Naive values passed in are assumed to already be UTC (e.g. datetime.utcnow()).
    Aware values in any timezone are converted to UTC before storing or comparing.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value
