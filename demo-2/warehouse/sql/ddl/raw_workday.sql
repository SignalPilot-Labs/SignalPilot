-- =====================================================================
-- Domain 10 — Workday (raw_workday)
-- NALA's HRIS. Employees (staff, NOT customers), org departments,
-- compensation history and time-off records.
--
-- Source system: Workday HCM (RaaS / Workday Reports-as-a-Service).
-- Naming follows Workday's real style: "Employee_ID" worker ids
-- ("WD-000123"), reference ids, effective-dated comp rows, PII-heavy
-- worker records (legal name, personal email, salary, national id).
-- Staff are generated with Faker — they are NOT in customer_master.
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS raw_workday;

-- ---------------------------------------------------------------------
-- Departments (org cost centers)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_workday.departments (
    department_id      text PRIMARY KEY,        -- "DEPT-ENG"
    name               text,                    -- Engineering / Compliance / Ops ...
    cost_center_code   text,                    -- "CC-1001"
    parent_department_id text,                  -- sparse
    location           text,                    -- London / Nairobi / Dakar
    headcount          integer,                 -- denormalized rollup (drifts)
    is_active          boolean
);

-- ---------------------------------------------------------------------
-- Employees — PII heavy worker records.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_workday.employees (
    employee_id        text PRIMARY KEY,        -- "WD-000123" worker id
    worker_uuid        text,                    -- Workday WID
    first_name         text,                    -- PII
    last_name          text,                    -- PII
    preferred_name     text,                    -- sparse PII
    work_email         text,                    -- name@nala.com (PII)
    personal_email     text,                    -- PII (sparse, dirty)
    phone              text,                    -- PII (dirty format)
    national_id        text,                    -- PII (ssn-style / NI / passport)
    national_id_hash   text,                    -- partial-governance mimic
    date_of_birth      date,                    -- PII
    gender             text,                    -- sparse
    department_id      text,                    -- -> departments.department_id
    job_title          text,                    -- Software Engineer / Compliance Analyst
    job_level          text,                    -- L3 / L4 / M1 ...
    management_chain   text,                    -- manager employee_id (sparse)
    location           text,                    -- London / Nairobi / Dakar / Remote
    employment_type    text,                    -- Regular / Contractor / Intern
    worker_status      text,                    -- Active / Terminated / On Leave
    hire_date          date,
    termination_date   date,                    -- sparse
    is_active          boolean,
    created_at         timestamptz,
    raw_attributes     jsonb                    -- denormalized worker snapshot
);

-- ---------------------------------------------------------------------
-- Compensation — effective-dated comp rows (one+ per employee).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_workday.compensation (
    compensation_id    bigint PRIMARY KEY,
    employee_id        text,                    -- -> employees.employee_id
    effective_date     date,                    -- effective-dated
    end_date           date,                    -- sparse (null = current)
    pay_type           text,                    -- Salary / Hourly
    base_pay           numeric(18,2),           -- PII (salary amount)
    currency           text,                    -- GBP / USD / KES ...
    pay_frequency      text,                    -- Annual / Monthly
    bonus_target_pct   numeric(6,2),            -- sparse
    equity_grant       numeric(18,2),           -- sparse (RSU value)
    change_reason      text,                    -- Hire / Merit / Promotion / Market Adj
    is_current         boolean,
    created_at         timestamptz
);

-- ---------------------------------------------------------------------
-- Time off — leave / PTO requests.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_workday.time_off (
    time_off_id        bigint PRIMARY KEY,
    employee_id        text,                    -- -> employees.employee_id
    leave_type         text,                    -- Annual / Sick / Parental / Unpaid
    start_date         date,
    end_date           date,
    days               numeric(6,2),            -- requested days (may be fractional)
    status             text,                    -- Approved / Pending / Cancelled / Denied
    approved_by        text,                    -- manager employee_id (sparse)
    requested_at       text,                    -- ISO string drift
    decided_at         timestamptz              -- sparse
);
