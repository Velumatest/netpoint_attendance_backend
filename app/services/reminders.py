from datetime import datetime, date, timedelta
from app.core.timeutil import LOCAL_TZ as TZ
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.models import Employee, AttendanceSession, LeaveRequest, EmployeeSchedule, PushToken, ReminderLog, UserAccount
from app.core.config import settings
from app.services.schedules import reminder_settings

_firebase_ready = False

def _send(tokens, title, body):
    global _firebase_ready
    if not settings.firebase_credentials_path or not tokens:
        return 0
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
        if not _firebase_ready:
            try: firebase_admin.get_app()
            except ValueError: firebase_admin.initialize_app(credentials.Certificate(settings.firebase_credentials_path))
            _firebase_ready = True
        sent = 0
        for token in tokens:
            try:
                messaging.send(messaging.Message(notification=messaging.Notification(title=title, body=body), token=token))
                sent += 1
            except Exception:
                # Invalid tokens are ignored here; clean-up can be done separately.
                pass
        return sent
    except Exception:
        return 0

def check_schedule_reminders():
    now = datetime.now(TZ)
    today = now.date()
    weekday = today.weekday()
    db = SessionLocal()
    try:
        schedules = db.scalars(select(EmployeeSchedule).where(
            EmployeeSchedule.enabled.is_(True), EmployeeSchedule.weekday == weekday,
            EmployeeSchedule.effective_from <= today,
            (EmployeeSchedule.effective_to.is_(None) | (EmployeeSchedule.effective_to >= today))
        )).all()
        rules: dict[int, dict] = {}
        for sch in schedules:
            # Reminder rules are per employee and apply to every one of their sessions.
            if sch.employee_id not in rules:
                rules[sch.employee_id] = reminder_settings(db, sch.employee_id)
            rule = rules[sch.employee_id]
            if not rule["enabled"]:
                continue
            # Approved leave suppresses reminders for the whole day.
            on_leave = db.scalar(select(LeaveRequest.id).where(
                LeaveRequest.employee_id == sch.employee_id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= today, LeaveRequest.end_date >= today
            ).limit(1))
            if on_leave:
                continue
            employee = db.get(Employee, sch.employee_id)
            if not employee or not employee.is_active:
                continue
            login_dt = datetime.combine(today, sch.login_time, TZ)
            logout_dt = datetime.combine(today, sch.logout_time, TZ)
            # Login is considered complete when a punch occurs in this scheduled window.
            start_window = login_dt - timedelta(minutes=30)
            login_done = db.scalar(select(AttendanceSession.id).where(
                AttendanceSession.employee_id == sch.employee_id,
                AttendanceSession.clock_in >= start_window,
                AttendanceSession.clock_in <= now
            ).limit(1))
            tokens = [x.token for x in db.scalars(select(PushToken).join(UserAccount, PushToken.user_id == UserAccount.id).where(UserAccount.employee_id == sch.employee_id)).all()]
            for event, due, complete, delay in (
                ("login", login_dt + timedelta(minutes=rule["login_delay_minutes"]), bool(login_done), rule["login_delay_minutes"]),
                ("logout", logout_dt + timedelta(minutes=rule["logout_delay_minutes"]), False, rule["logout_delay_minutes"]),
            ):
                if event == "logout":
                    open_session = db.scalar(select(AttendanceSession.id).where(
                        AttendanceSession.employee_id == sch.employee_id,
                        AttendanceSession.clock_in >= start_window,
                        AttendanceSession.clock_out.is_(None)
                    ).limit(1))
                    complete = not bool(open_session)
                if complete or now < due:
                    continue
                elapsed = int((now - due).total_seconds() // 60)
                reminder_number = min(1 + elapsed // max(rule["repeat_minutes"], 1), rule["max_reminders"])
                if elapsed // max(rule["repeat_minutes"], 1) >= rule["max_reminders"]:
                    continue
                already = db.scalar(select(ReminderLog.id).where(
                    ReminderLog.schedule_id == sch.id, ReminderLog.reminder_date == today,
                    ReminderLog.event_type == event, ReminderLog.reminder_number == reminder_number
                ).limit(1))
                if already:
                    continue
                title = "Attendance reminder"
                body = f"{sch.session_name}: please clock {event} for your scheduled {event} time."
                if _send(tokens, title, body) > 0:
                    db.add(ReminderLog(schedule_id=sch.id, reminder_date=today, event_type=event, reminder_number=reminder_number))
                    db.commit()
    finally:
        db.close()
