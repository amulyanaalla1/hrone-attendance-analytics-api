"""Employee Attendance & Analytics API, contract v2.0."""
import json
import os
import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal, Any

from bson import json_util
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=False)
db = client[MONGO_DB]
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
PRESENCE = ["PRESENT", "WFH", "ON_DUTY"]
STATUSES = PRESENCE + ["ABSENT", "LEAVE"]
EPOCH_MIN, EPOCH_MAX = 100_000_000_000, 4_102_444_800_000

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def ensure_indexes():
    # Index creation is idempotent. The natural keys enforce race safety.
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="ix_employee_department_code")
    db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="ix_employee_department_joined")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_code")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", DESCENDING)], name="ix_attendance_employee_date_desc")
    db.attendance_logs.create_index([("status", ASCENDING), ("date", ASCENDING)], name="ix_attendance_status_date")

# ------------------------------- validation --------------------------------
def validate_date_str(v: str) -> str:
    try:
        parsed = date.fromisoformat(v)
    except (ValueError, TypeError):
        raise ValueError("must be a valid YYYY-MM-DD date")
    if parsed.isoformat() != v:
        raise ValueError("must be a valid YYYY-MM-DD date")
    return v

def validate_month_str(v: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v or ""):
        raise ValueError("month must be YYYY-MM")
    return v

def valid_epoch(v):
    if v is None:
        return v
    if isinstance(v, bool) or not isinstance(v, int) or not EPOCH_MIN <= v <= EPOCH_MAX:
        raise ValueError("must be epoch milliseconds as an integer")
    return v

class EmployeeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field(default="18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: str
    @field_validator("joined_on")
    @classmethod
    def joined_date(cls, v): return validate_date_str(v)
    @model_validator(mode="after")
    def shifts_differ(self):
        if self.shift_start == self.shift_end: raise ValueError("shift_start must differ from shift_end")
        return self

class PunchInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str
    punched_at: Optional[StrictInt] = None
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"
    @field_validator("punched_at")
    @classmethod
    def timestamp(cls, v): return valid_epoch(v)

class PunchOutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str
    punched_at: Optional[StrictInt] = None
    @field_validator("punched_at")
    @classmethod
    def timestamp(cls, v): return valid_epoch(v)

class RegularizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None
    punch_in: Optional[StrictInt] = None
    punch_out: Optional[StrictInt] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)
    @field_validator("punch_in", "punch_out")
    @classmethod
    def timestamps(cls, v): return valid_epoch(v)

# ------------------------------- time helpers -------------------------------
def from_ms(ms: Optional[int]) -> Optional[datetime]:
    if ms is None: return None
    valid_epoch(ms)
    # Store UTC-naive BSON datetimes; truncate to whole seconds.
    return datetime.fromtimestamp(ms // 1000, tz=UTC).replace(tzinfo=None)

def to_ms(dt: Optional[datetime]) -> Optional[int]:
    if dt is None: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)

def truncate_seconds(dt: datetime) -> datetime:
    return dt.replace(microsecond=0)

def local_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)

def attendance_date_for(punch_in: datetime, employee: dict) -> str:
    local = local_dt(punch_in)
    start = time.fromisoformat(employee["shift_start"])
    end = time.fromisoformat(employee["shift_end"])
    d = local.date()
    if end <= start and local.time().replace(tzinfo=None) < end:
        d -= timedelta(days=1)
    return d.isoformat()

def shift_start_instant(day: str, employee: dict) -> datetime:
    d = date.fromisoformat(day)
    t = time.fromisoformat(employee["shift_start"])
    return datetime.combine(d, t, IST).astimezone(UTC).replace(tzinfo=None)

def shift_end_instant(day: str, employee: dict) -> datetime:
    d = date.fromisoformat(day)
    start = time.fromisoformat(employee["shift_start"])
    end = time.fromisoformat(employee["shift_end"])
    if end <= start: d += timedelta(days=1)
    return datetime.combine(d, end, IST).astimezone(UTC).replace(tzinfo=None)

def compute_late_minutes(punch_in: datetime, shift_start: str, attendance_day: Optional[str] = None) -> int:
    local = local_dt(punch_in)
    day = attendance_day or local.date().isoformat()
    start = datetime.combine(date.fromisoformat(day), time.fromisoformat(shift_start), IST).astimezone(UTC)
    delta = (punch_in.replace(tzinfo=UTC) - start).total_seconds()
    return int(delta // 60) if delta > 600 else 0

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    hours = Decimal(str((punch_out - punch_in).total_seconds())) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def compute_overtime(punch_out: datetime, shift_end: str, date_str: str, shift_start: Optional[str] = None) -> int:
    end_day = date.fromisoformat(date_str)
    if shift_start is not None and time.fromisoformat(shift_end) <= time.fromisoformat(shift_start):
        end_day += timedelta(days=1)
    end = datetime.combine(end_day, time.fromisoformat(shift_end), IST).astimezone(UTC).replace(tzinfo=None)
    seconds = (punch_out - end).total_seconds()
    return int(seconds // 60) if seconds >= 1800 else 0

def round_half_up(value, places=2):
    if value is None: return None
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))

def working_days(start: date, end: date) -> int:
    if end < start: return 0
    return sum(1 for i in range((end-start).days + 1) if (start + timedelta(days=i)).weekday() < 5)

def public_employee(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    if "created_at" in out: out["created_at"] = to_ms(out["created_at"])
    return out

def public_attendance(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["punch_in"] = to_ms(out.get("punch_in"))
    out["punch_out"] = to_ms(out.get("punch_out"))
    out["work_hours"] = out.get("work_hours")
    out["late_minutes"] = out.get("late_minutes", 0)
    out["overtime_minutes"] = out.get("overtime_minutes", 0)
    out["half_day"] = out.get("half_day", False)
    out["history"] = out.get("history", [])
    for h in out["history"]:
        h["at"] = to_ms(h.get("at"))
        for change in h.get("changes", {}).values():
            for k in ("from", "to"):
                if isinstance(change.get(k), datetime): change[k] = to_ms(change[k])
    return out

def http_error(status, detail): raise HTTPException(status_code=status, detail=detail)

def parse_month_bounds(month: str):
    validate_month_str(month)
    year, mon = map(int, month.split("-"))
    first = date(year, mon, 1)
    last = date(year, mon, monthrange(year, mon)[1])
    return first.isoformat(), last.isoformat(), first, last

# -------------------------------- endpoints ---------------------------------
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC).replace(tzinfo=None)
    try: db.employees.insert_one(doc)
    except DuplicateKeyError: http_error(409, "emp_code already exists")
    return public_employee(doc)

@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    q = {"department": department} if department is not None else {}
    total = db.employees.count_documents(q)
    docs = db.employees.find(q, {"_id": 0}).sort("emp_code", ASCENDING).skip((page-1)*page_size).limit(page_size)
    return {"items": [public_employee(d) for d in docs], "total": total, "page": page, "page_size": page_size}

@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp: http_error(404, "employee not found")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    ts = truncate_seconds(from_ms(body.punched_at if body.punched_at is not None else now_ms))
    day = attendance_date_for(ts, emp)
    doc = {"emp_code": body.emp_code, "date": day, "status": body.status, "punch_in": ts, "punch_out": None,
           "work_hours": None, "late_minutes": compute_late_minutes(ts, emp["shift_start"], day),
           "overtime_minutes": 0, "half_day": False, "history": []}
    try: db.attendance_logs.insert_one(doc)
    except DuplicateKeyError: http_error(409, "already punched in for this date")
    return public_attendance(doc)

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp: http_error(404, "employee not found")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    ts = truncate_seconds(from_ms(body.punched_at if body.punched_at is not None else now_ms))
    rec = db.attendance_logs.find_one({"emp_code": body.emp_code, "punch_in": {"$lte": ts}}, sort=[("punch_in", DESCENDING)])
    if not rec: http_error(404, "no punch-in found")
    if rec.get("punch_out") is not None: http_error(409, "attendance record already punched out")
    duration = (ts - rec["punch_in"]).total_seconds()
    if duration <= 0 or duration > 86400: http_error(422, "punch_out must be after punch_in and within 24 hours")
    hours = compute_work_hours(rec["punch_in"], ts)
    overtime = compute_overtime(ts, emp["shift_end"], rec["date"], emp["shift_start"])
    updated = db.attendance_logs.find_one_and_update(
        {"_id": rec["_id"], "punch_out": None},
        {"$set": {"punch_out": ts, "work_hours": hours, "overtime_minutes": overtime, "half_day": hours < 4.50}},
        return_document=ReturnDocument.AFTER)
    if updated is None: http_error(409, "attendance record already punched out")
    return public_attendance(updated)

@app.get("/attendance")
def list_attendance(emp_code: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None,
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    if date_from: validate_date_str(date_from)
    if date_to: validate_date_str(date_to)
    if date_from and date_to and date_from > date_to: http_error(422, "date_from must be <= date_to")
    q: dict[str, Any] = {}
    if emp_code is not None: q["emp_code"] = emp_code
    if status is not None: q["status"] = status
    if date_from or date_to:
        q["date"] = {}
        if date_from: q["date"]["$gte"] = date_from
        if date_to: q["date"]["$lte"] = date_to
    total = db.attendance_logs.count_documents(q)
    docs = db.attendance_logs.find(q).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page-1)*page_size).limit(page_size)
    return {"items": [public_attendance(d) for d in docs], "total": total, "page": page, "page_size": page_size}

@app.patch("/attendance/{emp_code}/{date}")
def regularize(emp_code: str, date: str, body: RegularizeIn):
    validate_date_str(date)
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp: http_error(404, "employee not found")
    old = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not old: http_error(404, "attendance record not found")
    status = body.status if body.status is not None else old.get("status", "PRESENT")
    pi = from_ms(body.punch_in) if body.punch_in is not None else old.get("punch_in")
    po = from_ms(body.punch_out) if body.punch_out is not None else old.get("punch_out")
    if status in ("ABSENT", "LEAVE"):
        if body.punch_in is not None or body.punch_out is not None: http_error(422, "ABSENT/LEAVE cannot include punch times")
        pi = po = None
    elif pi is None:
        http_error(422, "presence status requires punch_in")
    if pi is not None:
        pi = truncate_seconds(pi)
        if attendance_date_for(pi, emp) != date: http_error(422, "punch_in must belong to the attendance date")
    if po is not None:
        po = truncate_seconds(po)
        if pi is None or (po-pi).total_seconds() <= 0 or (po-pi).total_seconds() > 86400:
            http_error(422, "punch_out must be after punch_in and within 24 hours")
    late = compute_late_minutes(pi, emp["shift_start"], date) if pi is not None else 0
    hours = compute_work_hours(pi, po) if pi is not None and po is not None else None
    overtime = compute_overtime(po, emp["shift_end"], date, emp["shift_start"]) if po is not None else 0
    half = bool(hours is not None and hours < 4.50)
    new_values = {"status": status, "punch_in": pi, "punch_out": po, "work_hours": hours,
                  "late_minutes": late, "overtime_minutes": overtime, "half_day": half}
    changes = {}
    for key, new in new_values.items():
        oldval = old.get(key, False if key == "half_day" else 0 if key in ("late_minutes", "overtime_minutes") else None)
        if oldval != new:
            changes[key] = {"from": oldval, "to": new}
    if not changes: http_error(422, "request does not change the record")
    hist = {"at": datetime.now(UTC).replace(tzinfo=None), "by": body.regularized_by, "reason": body.reason, "changes": changes}
    # Optimistic compare-and-set; a concurrent loser gets 409 rather than losing history.
    filt = {"_id": old["_id"], "status": old.get("status"), "punch_in": old.get("punch_in"), "punch_out": old.get("punch_out"), "history": old.get("history", [])}
    updated = db.attendance_logs.find_one_and_update(filt, {"$set": new_values, "$push": {"history": hist}}, return_document=ReturnDocument.AFTER)
    if updated is None: http_error(409, "record changed concurrently; retry regularization")
    return public_attendance(updated)

# --------------------------- aggregation pipelines ---------------------------
def month_match(month: str):
    first, last, _, _ = parse_month_bounds(month)
    return {"date": {"$gte": first, "$lte": last}}

def monthly_pipeline(emp_code: str, month: str):
    return [
        {"$match": {"emp_code": emp_code, **month_match(month)}},
        {"$set": {"_dow": {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}}},
        {"$group": {"_id": None,
            "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$status", PRESENCE]}, {"$in": ["$_dow", [2,3,4,5,6]]}]}, {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]}, 0]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}}}}
    ]

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp: http_error(404, "employee not found")
    first_s, last_s, first, last = parse_month_bounds(month)
    start = max(first, date.fromisoformat(emp["joined_on"]))
    wd = working_days(start, last) if start <= last else 0
    agg = list(db.attendance_logs.aggregate(monthly_pipeline(emp_code, month)))
    row = agg[0] if agg else {}
    present = float(row.get("present_days", 0))
    pct = round_half_up(present / wd * 100, 2) if wd else None
    return {"emp_code": emp_code, "month": month, "working_days": wd, "present_days": round_half_up(present, 2),
            "leave_days": int(row.get("leave_days", 0)), "late_count": int(row.get("late_count", 0)),
            "total_late_minutes": int(row.get("total_late_minutes", 0)), "total_overtime_minutes": int(row.get("total_overtime_minutes", 0)),
            "attendance_pct": pct}

def department_summary_pipeline(month: str, department: Optional[str] = None):
    _, last, _, _ = parse_month_bounds(month)
    stages = [{"$match": {"joined_on": {"$lte": last}}}]
    if department is not None: stages[0]["$match"]["department"] = department
    stages += [
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", month+"-01"]}, {"$lte": ["$date", last]}]}}},
            {"$set": {"_dow": {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}}}], "as": "logs"}},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": "$department", "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$logs.status", PRESENCE]}, {"$in": ["$logs._dow", [2,3,4,5,6]]}]}, {"$cond": [{"$eq": ["$logs.half_day", True]}, 0.5, 1]}, 0]}},
            "hours_sum": {"$sum": {"$cond": [{"$and": [{"$in": ["$logs.status", PRESENCE]}, {"$ne": [{"$ifNull": ["$logs.work_hours", None]}, None]}]}, "$logs.work_hours", 0]}},
            "hours_count": {"$sum": {"$cond": [{"$and": [{"$in": ["$logs.status", PRESENCE]}, {"$ne": [{"$ifNull": ["$logs.work_hours", None]}, None]}]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$logs.late_minutes", 0]}},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}},
            "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}}}},
        {"$project": {"_id": 0, "department": "$_id", "headcount": {"$size": "$headcount"}, "present_days": 1,
            "avg_work_hours": {"$cond": [{"$gt": ["$hours_count", 0]}, {"$divide": ["$hours_sum", "$hours_count"]}, None]},
            "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1}},
        {"$sort": {"department": 1}}
    ]
    return stages

@app.get("/analytics/departments/summary")
def department_summary(month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), department: Optional[str] = None):
    parse_month_bounds(month)
    rows = list(db.employees.aggregate(department_summary_pipeline(month, department), allowDiskUse=True))
    for r in rows:
        r["present_days"] = round_half_up(r.get("present_days", 0), 2)
        r["avg_work_hours"] = round_half_up(r.get("avg_work_hours"), 2)
    return {"month": month, "items": rows}

def leaderboard_pipeline(month: str, limit: int, department: Optional[str] = None):
    first, last, _, _ = parse_month_bounds(month)
    pipeline = [
        {"$match": {"date": {"$gte": first, "$lte": last}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
                    "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}}}},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
    ]
    if department is not None: pipeline.append({"$match": {"employee.department": department}})
    pipeline += [
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {"_id": 0, "rank": 1, "emp_code": "$_id", "name": "$employee.name", "department": "$employee.department", "total_late_minutes": 1, "late_count": 1}}
    ]
    return pipeline

@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), limit: int = Query(10, ge=1, le=50), department: Optional[str] = None):
    parse_month_bounds(month)
    return {"month": month, "items": list(db.attendance_logs.aggregate(leaderboard_pipeline(month, limit, department), allowDiskUse=True))}

# Trend is computed in MongoDB: $documents seeds a calendar date, $densify fills gaps,
# $lookup aggregates department attendance/headcount per day, and $setWindowFields computes the rolling mean.
def trend_pipeline(department: str, start_s: str, end_s: str):
    start = datetime.combine(date.fromisoformat(start_s), time.min, UTC)
    end_exclusive = datetime.combine(date.fromisoformat(end_s) + timedelta(days=1), time.min, UTC)
    return [
        {"$documents": [{"date": start}]},
        {"$densify": {"field": "date", "range": {"step": 1, "unit": "day", "bounds": [start, end_exclusive]}}},
        {"$match": {"date": {"$lt": end_exclusive}}},
        {"$set": {
            "day": {"$dateToString": {"date": "$date", "format": "%Y-%m-%d", "timezone": "UTC"}},
            "is_working_day": {"$in": [{"$dayOfWeek": "$date"}, [2, 3, 4, 5, 6]]}
        }},
        {"$lookup": {
            "from": "employees", "let": {"day": "$day"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$department", department]}, {"$lte": ["$joined_on", "$$day"]}
                ]}}},
                {"$count": "n"}
            ], "as": "hc"
        }},
        {"$set": {"headcount": {"$ifNull": [{"$arrayElemAt": ["$hc.n", 0]}, 0]}}},
        {"$lookup": {
            "from": "attendance_logs", "let": {"day": "$day"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$date", "$$day"]}}},
                {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "e"}},
                {"$unwind": "$e"},
                {"$match": {"$expr": {"$eq": ["$e.department", department]}}},
                {"$group": {
                    "_id": None,
                    "present_count": {"$sum": {"$cond": [
                        {"$in": ["$status", PRESENCE]},
                        {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]}, 0
                    ]}},
                    "late_count": {"$sum": {"$cond": [
                        {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0
                    ]}}
                }}
            ], "as": "daystats"
        }},
        {"$set": {
            "present_count": {"$ifNull": [{"$arrayElemAt": ["$daystats.present_count", 0]}, 0]},
            "late_count": {"$ifNull": [{"$arrayElemAt": ["$daystats.late_count", 0]}, 0]}
        }},
        {"$set": {"attendance_rate": {"$cond": [
            {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
            {"$divide": ["$present_count", "$headcount"]}, None
        ]}}},
        {"$setWindowFields": {"sortBy": {"date": 1}, "output": {
            "_avg": {"$avg": "$attendance_rate", "window": {"documents": [-6, "current"]}}
        }}},
        {"$project": {
            "_id": 0, "date": "$day", "is_working_day": 1, "headcount": 1,
            "present_count": 1, "late_count": 1,
            "attendance_rate": {"$cond": [{"$ne": ["$attendance_rate", None]}, {"$round": ["$attendance_rate", 4]}, None]},
            "moving_avg_7d": {"$cond": [{"$ne": ["$_avg", None]}, {"$round": ["$_avg", 4]}, None]}
        }},
        {"$sort": {"date": 1}}
    ]

@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_date: Optional[str] = Query(None, alias="from"), to_date: Optional[str] = Query(None, alias="to")):
    if from_date is None or to_date is None: http_error(422, "from and to are required")
    validate_date_str(from_date); validate_date_str(to_date)
    d1, d2 = date.fromisoformat(from_date), date.fromisoformat(to_date)
    if d2 < d1: http_error(422, "to must be on or after from")
    if (d2-d1).days + 1 > 92: http_error(422, "date range cannot exceed 92 days")
    if not db.employees.find_one({"department": department}): http_error(404, "department not found")
    rows = list(db.aggregate(trend_pipeline(department, from_date, to_date), allowDiskUse=True))
    # MongoDB $round is ties-to-even; the contract asks half-up for rates.
    for r in rows:
        r["attendance_rate"] = round_half_up(r.get("attendance_rate"), 4)
        r["moving_avg_7d"] = round_half_up(r.get("moving_avg_7d"), 4)
    return {"department": department, "items": rows}

# Explain plans use executionStats and the same query/pipeline builders as the endpoints.
@app.get("/admin/explain/{endpoint}")
def explain(endpoint: Literal["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"],
            emp_code: Optional[str] = None, month: Optional[str] = None, department: Optional[str] = None,
            limit: int = Query(10, ge=1, le=50), date_from: Optional[str] = None, date_to: Optional[str] = None,
            status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None,
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            from_date: Optional[str] = Query(None, alias="from"), to_date: Optional[str] = Query(None, alias="to")):
    if endpoint == "attendance_list":
        if date_from: validate_date_str(date_from)
        if date_to: validate_date_str(date_to)
        if date_from and date_to and date_from > date_to: http_error(422, "date_from must be <= date_to")
        q = {}
        if emp_code is not None: q["emp_code"] = emp_code
        if status is not None: q["status"] = status
        if date_from or date_to:
            q["date"] = {}
            if date_from: q["date"]["$gte"] = date_from
            if date_to: q["date"]["$lte"] = date_to
        cmd = {"find": "attendance_logs", "filter": q, "sort": {"date": -1, "emp_code": 1}, "skip": (page-1)*page_size, "limit": page_size}
        raw = db.command("explain", cmd, verbosity="executionStats"); collection = "attendance_logs"
    else:
        if not month: http_error(422, "month is required")
        parse_month_bounds(month)
        if endpoint == "employee_monthly":
            if not emp_code: http_error(422, "emp_code is required")
            pipeline = monthly_pipeline(emp_code, month); collection = "attendance_logs"
        elif endpoint == "department_summary":
            pipeline = department_summary_pipeline(month, department); collection = "employees"
        elif endpoint == "late_leaderboard":
            pipeline = leaderboard_pipeline(month, limit, department); collection = "attendance_logs"
        else:
            if not department or not from_date or not to_date: http_error(422, "department, from, and to are required")
            validate_date_str(from_date); validate_date_str(to_date)
            if date.fromisoformat(to_date) < date.fromisoformat(from_date) or (date.fromisoformat(to_date)-date.fromisoformat(from_date)).days + 1 > 92: http_error(422, "invalid trend range")
            pipeline = trend_pipeline(department, from_date, to_date); collection = "$db.aggregate"
        if collection == "$db.aggregate":
            # Database-level $documents aggregation explain.
            raw = db.command("explain", {"aggregate": 1, "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}, verbosity="executionStats")
        else:
            raw = db.command("explain", {"aggregate": collection, "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}, verbosity="executionStats")
    return {"endpoint": endpoint, "collection": collection, "explain": json.loads(json_util.dumps(raw))}
