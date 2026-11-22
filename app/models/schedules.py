from datetime import date, time, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base
from app.db.types import UTCDateTime

class EmployeeSchedule(Base):
    __tablename__ = "employee_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)  # Monday=0 ... Sunday=6
    session_name: Mapped[str] = mapped_column(String(80), default="Work")
    login_time: Mapped[time] = mapped_column(Time)
    logout_time: Mapped[time] = mapped_column(Time)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Legacy per-session reminder values. Reminders now use EmployeeReminderSetting;
    # these columns stay only so existing databases need no ALTER TABLE.
    login_delay_minutes: Mapped[int] = mapped_column(Integer, default=5)
    logout_delay_minutes: Mapped[int] = mapped_column(Integer, default=5)
    repeat_minutes: Mapped[int] = mapped_column(Integer, default=30)
    max_reminders: Mapped[int] = mapped_column(Integer, default=2)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # False = that day is switched off

class EmployeeReminderSetting(Base):
    """Clock-in/out reminder rules for one employee, applied to all of their scheduled sessions."""
    __tablename__ = "employee_reminder_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    login_delay_minutes: Mapped[int] = mapped_column(Integer, default=5)
    logout_delay_minutes: Mapped[int] = mapped_column(Integer, default=5)
    repeat_minutes: Mapped[int] = mapped_column(Integer, default=30)
    max_reminders: Mapped[int] = mapped_column(Integer, default=2)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

class PushToken(Base):
    __tablename__ = "push_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id"), index=True)
    token: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(20), default="web")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)

class ReminderLog(Base):
    __tablename__ = "reminder_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("employee_schedules.id"), index=True)
    reminder_date: Mapped[date] = mapped_column(Date, index=True)
    event_type: Mapped[str] = mapped_column(String(20))
    reminder_number: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("schedule_id", "reminder_date", "event_type", "reminder_number", name="uq_schedule_reminder"),)
