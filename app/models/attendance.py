from datetime import datetime, time
from sqlalchemy import ForeignKey, Float, String, Text, Time
from app.db.types import UTCDateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base

class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    clock_in: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    clock_out: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    clock_in_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    clock_out_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Copy of the schedule taken at clock-in, so later schedule edits don't change past figures.
    # The shift this clock-in belongs to (local wall-clock times); null if it was a day off.
    scheduled_session: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scheduled_login: Mapped[time | None] = mapped_column(Time, nullable=True)
    scheduled_logout: Mapped[time | None] = mapped_column(Time, nullable=True)
    # Every shift of that day as JSON: [{"session_name","login_time","logout_time"}]; "[]" = day off.
    day_schedule: Mapped[str | None] = mapped_column(Text, nullable=True)
