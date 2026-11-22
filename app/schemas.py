from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

class EmployeeCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=40)
    full_name: str = Field(min_length=1, max_length=150)
    department: str | None = Field(default=None, max_length=100)

class EmployeeOut(BaseModel):
    id: int
    employee_code: str
    full_name: str
    department: str | None
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class AttendanceCreate(BaseModel):
    employee_id: int
    work_date: date
    status: str = Field(default="present", pattern="^(present|absent|late|half_day)$")
    check_in: datetime | None = None
    remarks: str | None = Field(default=None, max_length=255)

class AttendanceOut(BaseModel):
    id: int
    employee_id: int
    work_date: date
    status: str
    check_in: datetime | None
    remarks: str | None
    model_config = ConfigDict(from_attributes=True)
