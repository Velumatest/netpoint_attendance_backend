from datetime import date, datetime
from math import radians, sin, cos, asin, sqrt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.config import settings
from app.core.security import verify_password, make_token, hash_password
from app.core.timeutil import local_today, local_day_bounds
from app.models import Employee, AttendanceSession, UserAccount, LeaveType, LeaveRequest, SalaryRecord, Target, OfficeSetting

router=APIRouter(prefix="/api/v1")
oauth=OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def current_user(token:str=Depends(oauth), db:Session=Depends(get_db)):
    try:
        data=jwt.decode(token,settings.jwt_secret,algorithms=[settings.jwt_algorithm])
        user=db.get(UserAccount,int(data["sub"]))
        if not user or not user.is_active: raise ValueError()
        return user
    except (JWTError,ValueError,KeyError):
        raise HTTPException(401,"Invalid or expired login token")

def require(*roles):
    def dep(user:UserAccount=Depends(current_user)):
        if user.role not in roles: raise HTTPException(403,"You do not have permission")
        return user
    return dep

def visible_employee_ids(user, db):
    if user.role in ("admin","hr"): return None
    if user.role=="manager":
        return [e.id for e in db.scalars(select(Employee).where(Employee.manager_id==user.employee_id)).all()] + ([user.employee_id] if user.employee_id else [])
    return [user.employee_id] if user.employee_id else []

def can_view_employee(user, employee_id, db):
    ids=visible_employee_ids(user,db)
    return ids is None or employee_id in ids

class LoginIn(BaseModel):
    username:str
    password:str
class EmployeeIn(BaseModel):
    employee_code:str
    full_name:str
    department:str|None=None
    manager_id:int|None=None
    username:str
    temporary_password:str
    role:str="employee"
class PunchIn(BaseModel):
    comment:str|None=None
    latitude:float|None=None
    longitude:float|None=None
    accuracy:float|None=None
class LeaveIn(BaseModel):
    leave_type_id:int
    start_date:date
    end_date:date
    reason:str|None=None
class LeaveTypeIn(BaseModel):
    name:str
    approval_required:bool=True
    approver_role:str="manager"
    deduct_balance:bool=True
class SalaryIn(BaseModel):
    employee_id:int
    effective_from:date
    basic:float=0
    allowances:float=0
    deductions:float=0
    notes:str|None=None
class TargetIn(BaseModel):
    employee_id:int
    title:str
    period:str="monthly"
    target_value:float
    achieved_value:float=0
    start_date:date
    end_date:date
class OfficeIn(BaseModel):
    name:str="Main office"
    latitude:float
    longitude:float
    radius_meters:int=200
    gps_required:bool=True

@router.post("/auth/login")
def login(payload:LoginIn, db:Session=Depends(get_db)):
    user=db.scalar(select(UserAccount).where(UserAccount.username==payload.username))
    if not user or not verify_password(payload.password,user.password_hash) or not user.is_active:
        raise HTTPException(401,"Incorrect username or password")
    return {"access_token":make_token(user.id,user.role),"token_type":"bearer","role":user.role,"username":user.username,"employee_id":user.employee_id}

@router.get("/auth/me")
def me(user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    employee=db.get(Employee,user.employee_id) if user.employee_id else None
    return {"id":user.id,"username":user.username,"role":user.role,"employee_id":user.employee_id,"full_name":employee.full_name if employee else "Administrator"}

@router.get("/employees")
def employees(user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    ids=visible_employee_ids(user,db)
    stmt=select(Employee, UserAccount).outerjoin(UserAccount, UserAccount.employee_id == Employee.id).order_by(Employee.full_name)
    if ids is not None: stmt=stmt.where(Employee.id.in_(ids))
    rows=db.execute(stmt).all()
    return [{
        "id": e.id, "employee_code": e.employee_code, "full_name": e.full_name,
        "department": e.department, "manager_id": e.manager_id, "is_active": e.is_active,
        "username": account.username if account else "", "role": account.role if account else "employee",
        "account_active": account.is_active if account else False,
    } for e, account in rows]

@router.post("/employees")
def add_employee(p:EmployeeIn,user:UserAccount=Depends(require("admin")),db:Session=Depends(get_db)):
    if p.role not in ("manager","employee","hr"): raise HTTPException(400,"Role must be manager or employee")
    if db.scalar(select(Employee).where(Employee.employee_code==p.employee_code)): raise HTTPException(409,"Employee code already exists")
    if db.scalar(select(UserAccount).where(UserAccount.username==p.username)): raise HTTPException(409,"Username already exists")
    e=Employee(employee_code=p.employee_code,full_name=p.full_name,department=p.department,manager_id=p.manager_id)
    db.add(e); db.flush()
    u=UserAccount(username=p.username,password_hash=hash_password(p.temporary_password),role=p.role,employee_id=e.id)
    db.add(u); db.commit(); db.refresh(e); return e

class EmployeeUpdateIn(BaseModel):
    full_name: str | None = None
    department: str | None = None
    manager_id: int | None = None
    username: str | None = None
    role: str | None = None
    temporary_password: str | None = None
    is_active: bool | None = None

@router.put("/employees/{employee_id}")
def update_employee(employee_id: int, p: EmployeeUpdateIn, user: UserAccount = Depends(require("admin")), db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(404, "Employee not found")
    account = db.scalar(select(UserAccount).where(UserAccount.employee_id == employee_id))
    data = p.model_dump(exclude_unset=True)
    if "full_name" in data:
        if not data["full_name"] or not data["full_name"].strip():
            raise HTTPException(400, "Employee name cannot be empty")
        employee.full_name = data["full_name"].strip()
    if "department" in data:
        employee.department = data["department"] or None
    if "manager_id" in data:
        manager_id = data["manager_id"]
        if manager_id is not None and not db.get(Employee, manager_id):
            raise HTTPException(404, "Manager not found")
        employee.manager_id = manager_id
    if "is_active" in data:
        employee.is_active = bool(data["is_active"])
        if account:
            account.is_active = bool(data["is_active"])
    if account:
        if "username" in data and data["username"]:
            username = data["username"].strip()
            duplicate = db.scalar(select(UserAccount).where(UserAccount.username == username, UserAccount.id != account.id))
            if duplicate:
                raise HTTPException(409, "Username already exists")
            account.username = username
        if "role" in data and data["role"]:
            if data["role"] not in ("manager", "employee", "hr"):
                raise HTTPException(400, "Invalid employee role")
            account.role = data["role"]
        if data.get("temporary_password"):
            if len(data["temporary_password"]) < 10:
                raise HTTPException(400, "Password must contain at least 10 characters")
            account.password_hash = hash_password(data["temporary_password"])
    db.commit(); db.refresh(employee)
    return {"id": employee.id, "employee_code": employee.employee_code, "full_name": employee.full_name,
            "department": employee.department, "manager_id": employee.manager_id, "is_active": employee.is_active,
            "username": account.username if account else "", "role": account.role if account else "employee",
            "account_active": account.is_active if account else False}

@router.get("/attendance")
def attendance(work_date:date|None=None,date_from:date|None=None,date_to:date|None=None,employee_id:int|None=None,
               user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    """Sessions visible to the user. Filter by one local day (work_date) or an inclusive local
    date range (date_from/date_to), and optionally by employee."""
    ids=visible_employee_ids(user,db)
    q=select(AttendanceSession).order_by(AttendanceSession.clock_in.desc()).limit(2000)
    if ids is not None: q=q.where(AttendanceSession.employee_id.in_(ids))
    if employee_id is not None:
        if ids is not None and employee_id not in ids: raise HTTPException(403,"You cannot view this employee's attendance")
        q=q.where(AttendanceSession.employee_id==employee_id)
    if work_date: date_from=date_to=work_date
    if date_from and date_to and date_to<date_from: raise HTTPException(400,"date_to must be on or after date_from")
    if date_from: q=q.where(AttendanceSession.clock_in>=local_day_bounds(date_from)[0])
    if date_to: q=q.where(AttendanceSession.clock_in<local_day_bounds(date_to)[1])
    return db.scalars(q).all()

def gps_check(lat,lon,accuracy,db):
    office=db.scalar(select(OfficeSetting).order_by(OfficeSetting.id.desc()))
    if not office or not office.gps_required: return
    if lat is None or lon is None: raise HTTPException(400,"GPS location is required")
    if accuracy is not None and accuracy>200: raise HTTPException(400,"GPS accuracy is too low; try again outdoors")
    dlat=radians(lat-office.latitude); dlon=radians(lon-office.longitude)
    a=sin(dlat/2)**2+cos(radians(office.latitude))*cos(radians(lat))*sin(dlon/2)**2
    distance=6371000*2*asin(sqrt(a))
    if distance>office.radius_meters: raise HTTPException(403,f"Outside permitted office radius ({int(distance)} m away)")

@router.post("/attendance/clock-in")
def clock_in(p:PunchIn,user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    if not user.employee_id: raise HTTPException(400,"This account is not linked to an employee")
    gps_check(p.latitude,p.longitude,p.accuracy,db)
    open_session=db.scalar(select(AttendanceSession).where(AttendanceSession.employee_id==user.employee_id,AttendanceSession.clock_out.is_(None)))
    if open_session: raise HTTPException(409,"You are already clocked in")
    row=AttendanceSession(employee_id=user.employee_id,clock_in=datetime.utcnow(),clock_in_comment=p.comment,in_latitude=p.latitude,in_longitude=p.longitude,in_accuracy=p.accuracy)
    stamp_schedule(db,row)  # keep a copy of today's schedule on the record
    db.add(row); db.commit(); db.refresh(row); return row

@router.post("/attendance/{session_id}/clock-out")
def clock_out(session_id:int,p:PunchIn,user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    row=db.get(AttendanceSession,session_id)
    if not row or not can_view_employee(user,row.employee_id,db): raise HTTPException(404,"Attendance session not found")
    if user.role=="employee" and row.employee_id!=user.employee_id: raise HTTPException(403,"Not your attendance record")
    if row.clock_out: raise HTTPException(409,"Already clocked out")
    gps_check(p.latitude,p.longitude,p.accuracy,db)
    row.clock_out=datetime.utcnow(); row.clock_out_comment=p.comment
    row.out_latitude=p.latitude; row.out_longitude=p.longitude; row.out_accuracy=p.accuracy
    db.commit(); db.refresh(row); return row

@router.get("/attendance/open")
def open_session(user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    if not user.employee_id: return None
    return db.scalar(select(AttendanceSession).where(AttendanceSession.employee_id==user.employee_id,AttendanceSession.clock_out.is_(None)))

@router.get("/dashboard")
def dashboard(work_date:date|None=None,user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    day=work_date or local_today(); ids=visible_employee_ids(user,db)
    eq=select(Employee).where(Employee.is_active.is_(True))
    if ids is not None: eq=eq.where(Employee.id.in_(ids))
    emps=db.scalars(eq).all(); total=len(emps)
    start,end=local_day_bounds(day)
    sessions=db.scalars(select(AttendanceSession).where(AttendanceSession.clock_in>=start,AttendanceSession.clock_in<end)).all()
    present=len({s.employee_id for s in sessions if s.employee_id in {e.id for e in emps}})
    return {"work_date":day,"total_employees":total,"marked":present,"present":present,"absent":0,"not_marked":max(total-present,0)}

@router.post("/leave/types")
def create_leave_type(p:LeaveTypeIn,user:UserAccount=Depends(require("admin")),db:Session=Depends(get_db)):
    x=LeaveType(**p.model_dump()); db.add(x); db.commit(); db.refresh(x); return x
@router.get("/leave/types")
def list_leave_types(user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    return db.scalars(select(LeaveType).order_by(LeaveType.name)).all()
@router.post("/leave/requests")
def apply_leave(p:LeaveIn,user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    if not user.employee_id: raise HTTPException(400,"Employee account required")
    if p.end_date<p.start_date: raise HTTPException(400,"End date must be on or after start date")
    lt=db.get(LeaveType,p.leave_type_id)
    if not lt: raise HTTPException(404,"Leave type not found")
    x=LeaveRequest(employee_id=user.employee_id,**p.model_dump(),status="pending" if lt.approval_required else "approved")
    db.add(x); db.commit(); db.refresh(x); return x
@router.get("/leave/requests")
def list_leaves(user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    ids=visible_employee_ids(user,db); q=select(LeaveRequest).order_by(LeaveRequest.id.desc())
    if ids is not None: q=q.where(LeaveRequest.employee_id.in_(ids))
    return db.scalars(q.limit(500)).all()
@router.patch("/leave/requests/{request_id}/{decision}")
def review_leave(request_id:int,decision:str,user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    if decision not in ("approved","rejected"): raise HTTPException(400,"Invalid decision")
    x=db.get(LeaveRequest,request_id)
    if not x or not can_view_employee(user,x.employee_id,db): raise HTTPException(404,"Leave request not found")
    lt=db.get(LeaveType,x.leave_type_id)
    if user.role=="employee" or (lt.approver_role=="admin" and user.role!="admin") or (lt.approver_role=="manager" and user.role not in ("manager","admin")): raise HTTPException(403,"Not authorised to review")
    if user.role=="manager" and x.employee_id==user.employee_id: raise HTTPException(403,"Cannot approve your own leave")
    x.status=decision; x.reviewed_by=user.id; x.reviewed_at=datetime.utcnow(); db.commit(); return x

@router.post("/salary")
def save_salary(p:SalaryIn,user:UserAccount=Depends(require("admin","hr")),db:Session=Depends(get_db)):
    x=SalaryRecord(**p.model_dump()); db.add(x); db.commit(); db.refresh(x); return x
@router.get("/salary")
def list_salary(user:UserAccount=Depends(require("admin","hr")),db:Session=Depends(get_db)):
    return db.scalars(select(SalaryRecord).order_by(SalaryRecord.effective_from.desc())).all()
@router.post("/targets")
def save_target(p:TargetIn,user:UserAccount=Depends(require("admin","manager")),db:Session=Depends(get_db)):
    if not can_view_employee(user,p.employee_id,db): raise HTTPException(403,"Outside your team")
    x=Target(**p.model_dump()); db.add(x); db.commit(); db.refresh(x); return x
@router.get("/targets")
def list_targets(user:UserAccount=Depends(current_user),db:Session=Depends(get_db)):
    ids=visible_employee_ids(user,db); q=select(Target).order_by(Target.start_date.desc())
    if ids is not None: q=q.where(Target.employee_id.in_(ids))
    return db.scalars(q.limit(500)).all()
@router.put("/settings/office")
def set_office(p:OfficeIn,user:UserAccount=Depends(require("admin")),db:Session=Depends(get_db)):
    x=db.scalar(select(OfficeSetting).order_by(OfficeSetting.id.desc()))
    if x:
        for k,v in p.model_dump().items(): setattr(x,k,v)
    else: x=OfficeSetting(**p.model_dump()); db.add(x)
    db.commit(); db.refresh(x); return x
@router.get("/settings/office")
def get_office(user:UserAccount=Depends(require("admin")),db:Session=Depends(get_db)):
    return db.scalar(select(OfficeSetting).order_by(OfficeSetting.id.desc()))

# Employee work schedules: multiple sessions per weekday, with effective dates.
from datetime import time as time_type, timedelta
from app.models.schedules import EmployeeSchedule, EmployeeReminderSetting, PushToken
from app.services.schedules import stamp_schedule, week_on, validate_week, save_week, reminder_settings, active_on

class ScheduleIn(BaseModel):
    employee_id: int
    weekday: int = Field(ge=0, le=6)
    session_name: str = "Work"
    login_time: time_type
    logout_time: time_type
    effective_from: date
    effective_to: date | None = None
    login_delay_minutes: int = Field(default=5, ge=0, le=1440)
    logout_delay_minutes: int = Field(default=5, ge=0, le=1440)
    repeat_minutes: int = Field(default=30, ge=5, le=1440)
    max_reminders: int = Field(default=2, ge=1, le=10)
    enabled: bool = True

class PushTokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    platform: str = Field(default="web", pattern="^(web|android|ios)$")

@router.get("/schedules")
def list_schedules(employee_id: int | None = None, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)):
    q = select(EmployeeSchedule).order_by(EmployeeSchedule.employee_id, EmployeeSchedule.weekday, EmployeeSchedule.login_time)
    if user.role == "employee":
        q = q.where(EmployeeSchedule.employee_id == user.employee_id)
    elif user.role == "manager":
        ids = visible_employee_ids(user, db) or []
        q = q.where(EmployeeSchedule.employee_id.in_(ids))
    elif employee_id:
        q = q.where(EmployeeSchedule.employee_id == employee_id)
    return db.scalars(q).all()

class WeekSessionIn(BaseModel):
    session_name: str = Field(default="Work", max_length=80)
    login_time: time_type
    logout_time: time_type

class WeekDayIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    working: bool = True
    sessions: list[WeekSessionIn] = Field(default_factory=list, max_length=12)

class ReminderSettingsIn(BaseModel):
    enabled: bool = True
    login_delay_minutes: int = Field(default=5, ge=0, le=1440)
    logout_delay_minutes: int = Field(default=5, ge=0, le=1440)
    repeat_minutes: int = Field(default=30, ge=5, le=1440)
    max_reminders: int = Field(default=2, ge=1, le=10)

class WeekIn(BaseModel):
    employee_id: int
    effective_from: date
    days: list[WeekDayIn] = Field(max_length=7)
    reminders: ReminderSettingsIn | None = None

def _check_visible(user, employee_id, db):
    ids = visible_employee_ids(user, db)
    if ids is not None and employee_id not in ids: raise HTTPException(403, "You cannot view this employee's schedule")

@router.get("/schedules/week")
def get_week(employee_id: int, on: date | None = None, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)):
    """The employee's weekly schedule in effect on `on` (default today), with their reminder settings."""
    _check_visible(user, employee_id, db)
    if not db.get(Employee, employee_id): raise HTTPException(404, "Employee not found")
    return week_on(db, employee_id, on or local_today())

@router.put("/schedules/week")
def put_week(p: WeekIn, user: UserAccount = Depends(require("admin")), db: Session = Depends(get_db)):
    """Replace the employee's week from effective_from onwards; earlier dates keep their old schedule."""
    if not db.get(Employee, p.employee_id): raise HTTPException(404, "Employee not found")
    try: slots = validate_week([d.model_dump() for d in p.days])
    except ValueError as e: raise HTTPException(400, str(e))
    if p.reminders:
        row = db.scalar(select(EmployeeReminderSetting).where(EmployeeReminderSetting.employee_id == p.employee_id))
        if not row: row = EmployeeReminderSetting(employee_id=p.employee_id); db.add(row)
        for k, v in p.reminders.model_dump().items(): setattr(row, k, v)
        row.updated_at = datetime.utcnow()
    save_week(db, p.employee_id, p.effective_from, slots)
    return week_on(db, p.employee_id, max(p.effective_from, local_today()))

@router.get("/employees/{employee_id}/reminder-settings")
def get_reminder_settings(employee_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)):
    _check_visible(user, employee_id, db)
    if not db.get(Employee, employee_id): raise HTTPException(404, "Employee not found")
    return reminder_settings(db, employee_id)

@router.put("/employees/{employee_id}/reminder-settings")
def put_reminder_settings(employee_id: int, p: ReminderSettingsIn, user: UserAccount = Depends(require("admin")), db: Session = Depends(get_db)):
    if not db.get(Employee, employee_id): raise HTTPException(404, "Employee not found")
    row = db.scalar(select(EmployeeReminderSetting).where(EmployeeReminderSetting.employee_id == employee_id))
    if not row: row = EmployeeReminderSetting(employee_id=employee_id); db.add(row)
    for k, v in p.model_dump().items(): setattr(row, k, v)
    row.updated_at = datetime.utcnow(); db.commit()
    return reminder_settings(db, employee_id)

@router.get("/schedules/day")
def schedules_by_day(on: date | None = None, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)):
    """Every visible active employee's sessions on one date, with leave status."""
    day = on or local_today(); ids = visible_employee_ids(user, db)
    q = select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name)
    if ids is not None: q = q.where(Employee.id.in_(ids))
    employees = db.scalars(q).all(); emp_ids = [e.id for e in employees]
    rows = db.scalars(select(EmployeeSchedule).where(EmployeeSchedule.employee_id.in_(emp_ids), EmployeeSchedule.weekday == day.weekday(),
                                                     active_on(day)).order_by(EmployeeSchedule.login_time)).all() if emp_ids else []
    on_leave = set(db.scalars(select(LeaveRequest.employee_id).where(LeaveRequest.employee_id.in_(emp_ids), LeaveRequest.status == "approved",
                                                                    LeaveRequest.start_date <= day, LeaveRequest.end_date >= day)).all()) if emp_ids else set()
    out = []
    for e in employees:
        mine = [r for r in rows if r.employee_id == e.id]
        out.append({"employee_id": e.id, "full_name": e.full_name, "employee_code": e.employee_code, "department": e.department,
                    "working": any(r.enabled for r in mine), "on_leave": e.id in on_leave,
                    "sessions": [{"id": r.id, "session_name": r.session_name, "login_time": r.login_time.strftime("%H:%M"),
                                  "logout_time": r.logout_time.strftime("%H:%M"), "enabled": r.enabled} for r in mine]})
    return {"on": day, "weekday": day.weekday(), "employees": out}

@router.post("/schedules")
def create_schedule(p: ScheduleIn, user: UserAccount = Depends(require("admin")), db: Session = Depends(get_db)):
    if p.logout_time <= p.login_time:
        raise HTTPException(400, "Logout time must be later than login time; overnight shifts are not supported yet")
    if p.effective_to and p.effective_to < p.effective_from:
        raise HTTPException(400, "Effective-to date must be on or after effective-from date")
    if not db.get(Employee, p.employee_id):
        raise HTTPException(404, "Employee not found")
    row = EmployeeSchedule(**p.model_dump())
    db.add(row); db.commit(); db.refresh(row); return row

@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, p: ScheduleIn, user: UserAccount = Depends(require("admin")), db: Session = Depends(get_db)):
    row = db.get(EmployeeSchedule, schedule_id)
    if not row: raise HTTPException(404, "Schedule not found")
    if p.logout_time <= p.login_time: raise HTTPException(400, "Logout time must be later than login time")
    for key, value in p.model_dump().items(): setattr(row, key, value)
    db.commit(); db.refresh(row); return row

@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, user: UserAccount = Depends(require("admin")), db: Session = Depends(get_db)):
    row = db.get(EmployeeSchedule, schedule_id)
    if not row: raise HTTPException(404, "Schedule not found")
    db.delete(row); db.commit(); return {"ok": True}

@router.post("/notifications/register")
def register_push_token(p: PushTokenIn, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(PushToken).where(PushToken.token == p.token))
    if row:
        row.user_id = user.id; row.platform = p.platform; row.updated_at = datetime.utcnow()
    else:
        db.add(PushToken(user_id=user.id, token=p.token, platform=p.platform))
    db.commit(); return {"registered": True}

@router.delete("/notifications/register")
def unregister_push_token(token: str, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(PushToken).where(PushToken.token == token, PushToken.user_id == user.id))
    if row: db.delete(row); db.commit()
    return {"registered": False}

class GoogleLoginIn(BaseModel):
    credential: str

@router.post("/auth/google")
def google_login(p: GoogleLoginIn, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(503, "Google sign-in is not configured by the administrator")
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        # GOOGLE_CLIENT_ID may list several comma-separated IDs (web, Android, iOS).
        audiences = [x.strip() for x in settings.google_client_id.split(",") if x.strip()]
        claims = id_token.verify_oauth2_token(p.credential, google_requests.Request(), audiences)
        email = claims.get("email", "").strip().lower()
        if not claims.get("email_verified") or not email:
            raise ValueError("Google account email is not verified")
    except Exception:
        raise HTTPException(401, "Invalid Google sign-in token")
    # Access is deliberately restricted to an already provisioned active account.
    user = db.scalar(select(UserAccount).where(func.lower(UserAccount.username) == email))
    if not user or not user.is_active:
        raise HTTPException(403, "This Google email is not registered and activated by your administrator")
    return {"access_token": make_token(user.id, user.role), "token_type": "bearer", "role": user.role, "username": user.username, "employee_id": user.employee_id}
