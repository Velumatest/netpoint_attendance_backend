from sqlalchemy import String, Boolean, ForeignKey, Date, DateTime, Float, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date, datetime
from app.db.session import Base
from app.db.types import UTCDateTime

class UserAccount(Base):
    __tablename__ = "user_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20), default="employee")
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class LeaveType(Base):
    __tablename__ = "leave_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    approver_role: Mapped[str] = mapped_column(String(20), default="manager")
    deduct_balance: Mapped[bool] = mapped_column(Boolean, default=True)

class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("user_accounts.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

class SalaryRecord(Base):
    __tablename__ = "salary_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    basic: Mapped[float] = mapped_column(Numeric(12,2), default=0)
    allowances: Mapped[float] = mapped_column(Numeric(12,2), default=0)
    deductions: Mapped[float] = mapped_column(Numeric(12,2), default=0)
    notes: Mapped[str | None] = mapped_column(Text)

class Target(Base):
    __tablename__ = "targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    period: Mapped[str] = mapped_column(String(20), default="monthly")
    target_value: Mapped[float] = mapped_column(Float)
    achieved_value: Mapped[float] = mapped_column(Float, default=0)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

class OfficeSetting(Base):
    __tablename__ = "office_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="Main office")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_meters: Mapped[int] = mapped_column(default=200)
    gps_required: Mapped[bool] = mapped_column(Boolean, default=True)
