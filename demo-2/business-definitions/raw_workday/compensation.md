# raw_workday.compensation

**Source system:** Workday HCM — Compensation (effective-dated)
**Grain:** one row per employee per compensation change (effective-dated)
**Approx rows (demo scale):** ~1,000 (1–3 rows per employee)
**Loaded by:** warehouse/generators/gen_raw_workday.py

## Business definition
Effective-dated compensation history per employee: base pay, currency, bonus target, equity grants and the reason for each change (Hire, Merit, Promotion, Market Adjustment). The current row is flagged `is_current`. `base_pay` (salary) is sensitive PII.

## Known data-quality quirks
- Effective-dated: an employee has multiple rows; only one has `is_current = true` (and terminated employees may have none current).
- `end_date` is NULL on the current row.
- `bonus_target_pct` and `equity_grant` are sparse.
- Currency follows the employee's location (GBP for London, KES for Nairobi, XOF for Dakar).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| compensation_id | bigint | no | surrogate id (PK) |
| employee_id | text | no | -> employees.employee_id |
| effective_date | date | no | effective date |
| end_date | date | no | NULL = current row |
| pay_type | text | no | Salary / Hourly |
| base_pay | numeric(18,2) | yes | base pay (salary) |
| currency | text | no | pay currency |
| pay_frequency | text | no | Annual / Monthly |
| bonus_target_pct | numeric(6,2) | no | bonus target % (sparse) |
| equity_grant | numeric(18,2) | no | RSU value (sparse) |
| change_reason | text | no | Hire/Merit/Promotion/Market Adjustment |
| is_current | boolean | no | current comp row flag |
| created_at | timestamptz | no | record creation |

## Joins / lineage
- Joins to `raw_workday.employees` on `employee_id`.
