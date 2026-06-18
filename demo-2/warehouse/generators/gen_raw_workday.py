"""
Domain 10 — raw_workday generator.

HRIS: departments, employees (staff — NOT customers, generated with Faker),
effective-dated compensation, and time_off. PII heavy: legal name, personal
email, phone, national id, DOB, salary. Workday quirks: "WD-000123" worker
ids, effective-dated comp rows, ISO-string time-off timestamps, partial
governance (national_id alongside national_id_hash).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from faker import Faker

from common import (
    N, SCALE, connect, ensure_schema, apply_ddl_file, truncate, bulk_copy,
    rng, maybe_null, dirty_email, dirty_phone, ts_iso, EPOCH_END,
)

_DDL = Path(__file__).resolve().parent.parent / "sql" / "ddl" / "raw_workday.sql"

# Department -> (location, base currency, salary band low/high in local ccy)
DEPARTMENTS = [
    ("DEPT-ENG", "Engineering", "London", "GBP", 55000, 140000),
    ("DEPT-PROD", "Product", "London", "GBP", 60000, 150000),
    ("DEPT-COMP", "Compliance", "London", "GBP", 50000, 130000),
    ("DEPT-OPS", "Operations", "Nairobi", "KES", 1800000, 7200000),
    ("DEPT-FIN", "Finance", "London", "GBP", 55000, 135000),
    ("DEPT-PPL", "People", "London", "GBP", 45000, 110000),
    ("DEPT-MKT", "Marketing", "London", "GBP", 48000, 120000),
    ("DEPT-CS", "Customer Support", "Dakar", "XOF", 6000000, 18000000),
    ("DEPT-TREAS", "Treasury", "London", "GBP", 70000, 160000),
    ("DEPT-DATA", "Data & Analytics", "Nairobi", "KES", 2400000, 9600000),
]
LOCATIONS = ["London", "Nairobi", "Dakar", "Remote"]
TITLES = {
    "DEPT-ENG": ["Software Engineer", "Senior Software Engineer", "Staff Engineer",
                 "Engineering Manager"],
    "DEPT-PROD": ["Product Manager", "Senior PM", "Product Designer"],
    "DEPT-COMP": ["Compliance Analyst", "AML Officer", "MLRO", "KYC Specialist"],
    "DEPT-OPS": ["Operations Associate", "Payments Ops Lead", "Ops Manager"],
    "DEPT-FIN": ["Financial Analyst", "Accountant", "Finance Manager", "Controller"],
    "DEPT-PPL": ["People Partner", "Recruiter", "People Ops Lead"],
    "DEPT-MKT": ["Marketing Manager", "Growth Marketer", "Content Lead"],
    "DEPT-CS": ["Support Agent", "Support Team Lead", "CX Manager"],
    "DEPT-TREAS": ["Treasury Analyst", "Treasury Manager"],
    "DEPT-DATA": ["Data Analyst", "Data Engineer", "Analytics Lead"],
}
LEVELS = ["L2", "L3", "L4", "L5", "M1", "M2"]
EMP_TYPE = ["Regular", "Regular", "Regular", "Contractor", "Intern"]
STATUS = ["Active", "Active", "Active", "Active", "On Leave", "Terminated"]
LEAVE_TYPES = ["Annual", "Annual", "Sick", "Parental", "Unpaid", "Compassionate"]
LEAVE_STATUS = ["Approved", "Approved", "Approved", "Pending", "Cancelled", "Denied"]
CHANGE_REASON = ["Hire", "Merit", "Promotion", "Market Adjustment"]

# Number of employees scales modestly (a company, not a customer base).
_EMP_COUNT = {"test": 120}.get(SCALE, 600 if SCALE == "demo" else 2500)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _emp_record(k):
    """Deterministically build one employee + derived comp/time-off seeds."""
    r = rng("wd_emp", k)
    f = Faker()
    Faker.seed((42, "wd_emp", k).__hash__() & 0xFFFFFFFF)
    dept = DEPARTMENTS[r.randrange(len(DEPARTMENTS))]
    dept_id, dept_name, loc, ccy, lo, hi = dept
    first = f.first_name()
    last = f.last_name()
    eid = f"WD-{k:06d}"
    status = r.choice(STATUS)
    hire = f.date_between(start_date="-7y", end_date="-30d")
    term = None
    if status == "Terminated":
        term = f.date_between(start_date=hire, end_date="today")
    nid = f.bothify(text="??######?", letters="ABCDEFGH").upper()
    return {
        "r": r, "k": k, "eid": eid, "first": first, "last": last,
        "dept_id": dept_id, "loc": loc if r.random() > 0.15 else "Remote",
        "ccy": ccy, "lo": lo, "hi": hi, "status": status, "hire": hire,
        "term": term, "nid": nid,
        "work_email": f"{first.lower()}.{last.lower()}@nala.com",
        "personal_email": f"{first.lower()}.{last.lower()}{r.randint(1,99)}@gmail.com",
        "phone": f"+44{r.randint(7000000000, 7999999999)}",
        "dob": f.date_of_birth(minimum_age=21, maximum_age=64),
        "title": r.choice(TITLES[dept_id]),
        "level": r.choice(LEVELS),
    }


def _gen_departments():
    for dept_id, name, loc, ccy, lo, hi in DEPARTMENTS:
        r = rng("wd_dept", dept_id)
        yield (dept_id, name, f"CC-{abs(hash(dept_id)) % 9000 + 1000}", None,
               loc, r.randint(8, 90), True)


def _gen_employees():
    for k in range(_EMP_COUNT):
        e = _emp_record(k)
        r = e["r"]
        attrs = {"worker_id": e["eid"], "department": e["dept_id"],
                 "status": e["status"], "level": e["level"]}
        yield (
            e["eid"],
            f"wd-wid-{_hash(e['eid'])[:24]}",
            e["first"],
            e["last"],
            maybe_null(e["first"], 0.7, r),
            e["work_email"],
            dirty_email(maybe_null(e["personal_email"], 0.2, r), r),
            dirty_phone(e["phone"], r),
            e["nid"],
            _hash(e["nid"]),
            e["dob"],
            maybe_null(r.choice(["Male", "Female", "Non-binary"]), 0.25, r),
            e["dept_id"],
            e["title"],
            e["level"],
            maybe_null(f"WD-{r.randrange(_EMP_COUNT):06d}", 0.2, r),
            e["loc"],
            r.choice(EMP_TYPE),
            e["status"],
            e["hire"],
            e["term"],
            e["status"] != "Terminated",
            dt.datetime.combine(e["hire"], dt.time(9, 0)),
            json.dumps(attrs),
        )


def _gen_compensation():
    comp_id = 1
    for k in range(_EMP_COUNT):
        e = _emp_record(k)
        r = e["r"]
        n_rows = r.choice([1, 1, 2, 2, 3])
        eff = e["hire"]
        cur = round(r.uniform(e["lo"], e["hi"]), 2)
        for j in range(n_rows):
            is_last = (j == n_rows - 1)
            end = None if is_last else (eff + dt.timedelta(days=r.randint(180, 540)))
            reason = "Hire" if j == 0 else r.choice(CHANGE_REASON[1:])
            yield (
                comp_id, e["eid"], eff, end,
                "Salary" if e["loc"] != "Remote" or r.random() > 0.1 else "Hourly",
                round(cur, 2), e["ccy"], "Annual",
                maybe_null(round(r.uniform(5, 25), 2), 0.4, r),
                maybe_null(round(r.uniform(5000, 80000), 2), 0.6, r),
                reason, is_last and e["status"] != "Terminated",
                dt.datetime.combine(eff, dt.time(0, 0)),
            )
            comp_id += 1
            if end:
                eff = end
                cur = cur * r.uniform(1.03, 1.18)


def _gen_time_off():
    to_id = 1
    for k in range(_EMP_COUNT):
        e = _emp_record(k)
        r = e["r"]
        n_rows = r.choice([0, 1, 2, 3, 4, 5])
        for _ in range(n_rows):
            start = e["hire"] + dt.timedelta(days=r.randint(30, 2000))
            if start > EPOCH_END:
                start = EPOCH_END - dt.timedelta(days=r.randint(1, 200))
            days = r.choice([0.5, 1, 1, 2, 3, 5, 5, 10])
            end = start + dt.timedelta(days=int(max(1, days)))
            status = r.choice(LEAVE_STATUS)
            req = dt.datetime.combine(start - dt.timedelta(days=r.randint(1, 30)),
                                      dt.time(10, 0))
            decided = (req + dt.timedelta(days=r.randint(0, 5))
                       if status in ("Approved", "Denied") else None)
            yield (
                to_id, e["eid"], r.choice(LEAVE_TYPES), start, end, float(days),
                status, maybe_null(f"WD-{r.randrange(_EMP_COUNT):06d}", 0.3, r),
                ts_iso(req), decided,
            )
            to_id += 1


DEPT_COLS = ["department_id", "name", "cost_center_code", "parent_department_id",
             "location", "headcount", "is_active"]
EMP_COLS = ["employee_id", "worker_uuid", "first_name", "last_name",
            "preferred_name", "work_email", "personal_email", "phone",
            "national_id", "national_id_hash", "date_of_birth", "gender",
            "department_id", "job_title", "job_level", "management_chain",
            "location", "employment_type", "worker_status", "hire_date",
            "termination_date", "is_active", "created_at", "raw_attributes"]
COMP_COLS = ["compensation_id", "employee_id", "effective_date", "end_date",
             "pay_type", "base_pay", "currency", "pay_frequency",
             "bonus_target_pct", "equity_grant", "change_reason", "is_current",
             "created_at"]
TO_COLS = ["time_off_id", "employee_id", "leave_type", "start_date", "end_date",
           "days", "status", "approved_by", "requested_at", "decided_at"]


def main(conn):
    ensure_schema(conn, "raw_workday")
    apply_ddl_file(conn, _DDL)
    truncate(conn, "raw_workday.time_off", "raw_workday.compensation",
             "raw_workday.employees", "raw_workday.departments")
    d = bulk_copy(conn, "raw_workday.departments", DEPT_COLS, _gen_departments())
    e = bulk_copy(conn, "raw_workday.employees", EMP_COLS, _gen_employees())
    c = bulk_copy(conn, "raw_workday.compensation", COMP_COLS, _gen_compensation())
    t = bulk_copy(conn, "raw_workday.time_off", TO_COLS, _gen_time_off())
    print(f"[raw_workday] scale={SCALE} departments={d} employees={e} "
          f"compensation={c} time_off={t}")


if __name__ == "__main__":
    c = connect()
    main(c)
    c.close()
