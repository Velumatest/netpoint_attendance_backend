"""Weekly work schedules and per-employee reminder settings.

A schedule "version" is the set of EmployeeSchedule rows of one employee that are in effect on a
given date (effective_from <= date <= effective_to). Saving a week from date D ends the rows that
were running at D on D-1 and starts new rows on D, so earlier dates keep the schedule they had.
"""
import json
from dataclasses import dataclass
from datetime import date, time, timedelta, timezone
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.core.timeutil import LOCAL_TZ
from app.models import AttendanceSession, EmployeeSchedule, EmployeeReminderSetting, ReminderLog

REMINDER_DEFAULTS = {"enabled": True, "login_delay_minutes": 5, "logout_delay_minutes": 5, "repeat_minutes": 30, "max_reminders": 2}


def reminder_settings(db: Session, employee_id: int) -> dict:
    row = db.scalar(select(EmployeeReminderSetting).where(EmployeeReminderSetting.employee_id == employee_id))
    if not row:
        return {"employee_id": employee_id, **REMINDER_DEFAULTS, "is_default": True}
    return {"employee_id": employee_id, "enabled": row.enabled, "login_delay_minutes": row.login_delay_minutes,
            "logout_delay_minutes": row.logout_delay_minutes, "repeat_minutes": row.repeat_minutes,
            "max_reminders": row.max_reminders, "is_default": False}


def backfill_reminder_settings(db: Session) -> int:
    """One-off upgrade: employees who only have the old per-session reminder values get an
    employee-level row copied from their most recently started session."""
    have = set(db.scalars(select(EmployeeReminderSetting.employee_id)).all())
    latest: dict[int, EmployeeSchedule] = {}
    for s in db.scalars(select(EmployeeSchedule).order_by(EmployeeSchedule.effective_from, EmployeeSchedule.id)).all():
        latest[s.employee_id] = s
    added = 0
    for emp_id, s in latest.items():
        if emp_id in have:
            continue
        db.add(EmployeeReminderSetting(employee_id=emp_id, enabled=True, login_delay_minutes=s.login_delay_minutes,
                                       logout_delay_minutes=s.logout_delay_minutes, repeat_minutes=max(5, s.repeat_minutes),
                                       max_reminders=max(1, s.max_reminders)))
        added += 1
    if added:
        db.commit()
    return added


def active_on(day: date):
    """SQL condition: schedule row in effect on `day`."""
    return (EmployeeSchedule.effective_from <= day) & or_(EmployeeSchedule.effective_to.is_(None), EmployeeSchedule.effective_to >= day)


def week_on(db: Session, employee_id: int, day: date) -> dict:
    rows = db.scalars(select(EmployeeSchedule).where(EmployeeSchedule.employee_id == employee_id, active_on(day))
                      .order_by(EmployeeSchedule.weekday, EmployeeSchedule.login_time)).all()
    days = []
    for wd in range(7):
        sessions = [r for r in rows if r.weekday == wd]
        days.append({"weekday": wd, "working": any(r.enabled for r in sessions),
                     "sessions": [{"id": r.id, "session_name": r.session_name, "login_time": r.login_time.strftime("%H:%M"),
                                   "logout_time": r.logout_time.strftime("%H:%M")} for r in sessions]})
    next_change = db.scalar(select(EmployeeSchedule.effective_from).where(
        EmployeeSchedule.employee_id == employee_id, EmployeeSchedule.effective_from > day).order_by(EmployeeSchedule.effective_from).limit(1))
    ends = [r.effective_to for r in rows if r.effective_to]
    if ends and (next_change is None or min(ends) + timedelta(days=1) < next_change):
        next_change = min(ends) + timedelta(days=1)
    return {"employee_id": employee_id, "on": day,
            "effective_from": max((r.effective_from for r in rows), default=None),
            "next_change": next_change, "days": days, "reminders": reminder_settings(db, employee_id)}


@dataclass(frozen=True)
class Slot:
    weekday: int
    session_name: str
    login_time: time
    logout_time: time
    enabled: bool


def validate_week(days: list[dict]) -> list[Slot]:
    """Turns the editor payload into slots, or raises ValueError with a readable message."""
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    seen, slots = set(), []
    for d in days:
        wd = d["weekday"]
        if wd in seen:
            raise ValueError(f"{names[wd]} appears twice")
        seen.add(wd)
        sessions = sorted(d["sessions"], key=lambda s: s["login_time"])
        if d["working"] and not sessions:
            raise ValueError(f"{names[wd]} is marked as working but has no sessions")
        for i, s in enumerate(sessions):
            if s["logout_time"] <= s["login_time"]:
                raise ValueError(f"{names[wd]}: {s['session_name']} must end after it starts (overnight shifts aren't supported yet)")
            if i and s["login_time"] < sessions[i - 1]["logout_time"]:
                raise ValueError(f"{names[wd]}: {s['session_name']} overlaps {sessions[i - 1]['session_name']}")
            slots.append(Slot(wd, s["session_name"].strip() or "Work", s["login_time"], s["logout_time"], bool(d["working"])))
    return slots


def save_week(db: Session, employee_id: int, effective_from: date, slots: list[Slot]) -> None:
    """Make `slots` the employee's schedule from `effective_from` onwards (open-ended)."""
    rows = db.scalars(select(EmployeeSchedule).where(
        EmployeeSchedule.employee_id == employee_id,
        or_(EmployeeSchedule.effective_to.is_(None), EmployeeSchedule.effective_to >= effective_from))).all()
    wanted = list(slots)
    for r in rows:
        slot = Slot(r.weekday, r.session_name, r.login_time, r.logout_time, r.enabled)
        if slot in wanted:
            # Unchanged session: keep the row (and its reminder history) and make it run on.
            wanted.remove(slot)
            if r.effective_from > effective_from:
                r.effective_from = effective_from
            r.effective_to = None
        elif r.effective_from < effective_from:
            r.effective_to = effective_from - timedelta(days=1)  # history stays as it was
        else:
            # Starts on/after the new date and is no longer wanted: remove it with its reminder log.
            for log in db.scalars(select(ReminderLog).where(ReminderLog.schedule_id == r.id)).all():
                db.delete(log)
            db.flush()
            db.delete(r)
    for s in wanted:
        db.add(EmployeeSchedule(employee_id=employee_id, weekday=s.weekday, session_name=s.session_name,
                                login_time=s.login_time, logout_time=s.logout_time, effective_from=effective_from,
                                effective_to=None, enabled=s.enabled))
    db.commit()


# ---------------------------------------------------------------------------
# Schedule copy stored on attendance records
# ---------------------------------------------------------------------------

def day_plan(db: Session, employee_id: int, day: date) -> list[dict]:
    """The employee's working shifts on one date (empty = day off), earliest first."""
    rows = db.scalars(select(EmployeeSchedule).where(
        EmployeeSchedule.employee_id == employee_id, EmployeeSchedule.weekday == day.weekday(),
        EmployeeSchedule.enabled.is_(True), active_on(day)).order_by(EmployeeSchedule.login_time)).all()
    return [{"session_name": r.session_name, "login_time": r.login_time.strftime("%H:%M"),
             "logout_time": r.logout_time.strftime("%H:%M")} for r in rows]


def stamp_schedule(db: Session, row: AttendanceSession) -> None:
    """Copy the day's schedule onto an attendance record and pick the shift its clock-in belongs to:
    the first shift that hasn't ended yet at clock-in time, or the last shift if all have ended."""
    ci = row.clock_in if row.clock_in.tzinfo else row.clock_in.replace(tzinfo=timezone.utc)  # naive = UTC
    local = ci.astimezone(LOCAL_TZ)
    plan = day_plan(db, row.employee_id, local.date())
    row.day_schedule = json.dumps(plan)
    now = local.strftime("%H:%M")
    shift = next((s for s in plan if s["logout_time"] > now), plan[-1] if plan else None)
    row.scheduled_session = shift["session_name"] if shift else None
    row.scheduled_login = time.fromisoformat(shift["login_time"]) if shift else None
    row.scheduled_logout = time.fromisoformat(shift["logout_time"]) if shift else None


def backfill_attendance_schedules(db: Session) -> int:
    """Records made before the copy existed get it from the schedule history of their date."""
    rows = db.scalars(select(AttendanceSession).where(AttendanceSession.day_schedule.is_(None))).all()
    for r in rows:
        stamp_schedule(db, r)
    if rows:
        db.commit()
    return len(rows)
