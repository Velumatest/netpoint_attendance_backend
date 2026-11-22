from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base, engine, SessionLocal
from app import models
from app.models.hr import UserAccount
from app.api.routes import router
from apscheduler.schedulers.background import BackgroundScheduler
from app.core.timeutil import LOCAL_TZ
from app.services.reminders import check_schedule_reminders
from app.services.schedules import backfill_reminder_settings, backfill_attendance_schedules
from app.db.migrate import add_missing_columns

scheduler = BackgroundScheduler(timezone=LOCAL_TZ)

app=FastAPI(title=settings.app_name,version="1.0.0")
origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine)  # new nullable columns on existing tables
    db=SessionLocal()
    try:
        if not db.scalar(select(UserAccount).where(UserAccount.username==settings.admin_username)):
            db.add(UserAccount(username=settings.admin_username,password_hash=hash_password(settings.admin_password),role="admin"))
            db.commit()
        backfill_reminder_settings(db)  # copy old per-session reminder values to the employee level
        backfill_attendance_schedules(db)  # schedule copy on records made before it was stored
    finally: db.close()
    if not scheduler.running:
        scheduler.add_job(check_schedule_reminders, "interval", minutes=1, id="attendance_reminders", max_instances=1, coalesce=True)
        scheduler.start()

@app.on_event("shutdown")
def shutdown():
    if scheduler.running: scheduler.shutdown(wait=False)

@app.get("/health")
def health(): return {"status":"ok","service":settings.app_name}
app.include_router(router)
