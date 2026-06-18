# raw_workday.employees

**Source system:** Workday HCM — Worker record (RaaS export)
**Grain:** one row per employee (worker)
**Approx rows (demo scale):** ~600
**Loaded by:** warehouse/generators/gen_raw_workday.py

## Business definition
NALA's staff master in Workday. **Employees are NOT customers** — they are generated separately with Faker and do not appear in `customer_master`. PII-heavy worker records: legal name, work + personal email, phone, national id, DOB, plus org placement and employment status.

## Known data-quality quirks
- `national_id` is stored alongside a `national_id_hash` (SHA-256) to mimic partial governance.
- `personal_email` is sparse and dirtied (casing/space drift); `phone` is dirtied format.
- `termination_date` only populated for `worker_status = 'Terminated'`.
- `management_chain` (manager employee_id) is sparse and free-text, not an enforced FK.
- `preferred_name`, `gender` sparse.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| employee_id | text | no | "WD-000123" worker id (PK) |
| worker_uuid | text | no | Workday WID |
| first_name | text | yes | legal first name |
| last_name | text | yes | legal last name |
| preferred_name | text | yes | preferred name (sparse) |
| work_email | text | yes | name@nala.com |
| personal_email | text | yes | personal email (sparse, dirty) |
| phone | text | yes | phone (dirty format) |
| national_id | text | yes | ssn/NI/passport-style id |
| national_id_hash | text | no | SHA-256 of national_id |
| date_of_birth | date | yes | DOB |
| gender | text | yes | gender (sparse) |
| department_id | text | no | -> departments.department_id |
| job_title | text | no | job title |
| job_level | text | no | L2/L3/M1… |
| management_chain | text | no | manager employee_id (sparse) |
| location | text | no | London/Nairobi/Dakar/Remote |
| employment_type | text | no | Regular/Contractor/Intern |
| worker_status | text | no | Active/Terminated/On Leave |
| hire_date | date | no | hire date |
| termination_date | date | no | termination (sparse) |
| is_active | boolean | no | active flag |
| created_at | timestamptz | no | record creation |
| raw_attributes | jsonb | no | denormalized worker snapshot |

## Joins / lineage
- Joins to `raw_workday.departments` on `department_id`, `raw_workday.compensation` and `raw_workday.time_off` on `employee_id`.
- NO join to `customer_master` — staff are a separate population.
