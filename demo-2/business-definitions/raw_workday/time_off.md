# raw_workday.time_off

**Source system:** Workday HCM — Time Off / Absence request
**Grain:** one row per time-off request
**Approx rows (demo scale):** ~1,500
**Loaded by:** warehouse/generators/gen_raw_workday.py

## Business definition
Leave and PTO requests per employee: annual, sick, parental, unpaid and compassionate leave, with the approval workflow status. Used for absence reporting and capacity planning.

## Known data-quality quirks
- `requested_at` is an ISO string (not timestamptz); `decided_at` is timestamptz and sparse (only set for Approved/Denied).
- `days` may be fractional (half-days).
- `approved_by` (manager employee_id) is sparse, free text, not an enforced FK.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| time_off_id | bigint | no | surrogate id (PK) |
| employee_id | text | no | -> employees.employee_id |
| leave_type | text | no | Annual/Sick/Parental/Unpaid/Compassionate |
| start_date | date | no | leave start |
| end_date | date | no | leave end |
| days | numeric(6,2) | no | requested days (may be fractional) |
| status | text | no | Approved/Pending/Cancelled/Denied |
| approved_by | text | no | manager employee_id (sparse) |
| requested_at | text | no | ISO string |
| decided_at | timestamptz | no | decision timestamp (sparse) |

## Joins / lineage
- Joins to `raw_workday.employees` on `employee_id`.
