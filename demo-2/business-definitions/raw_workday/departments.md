# raw_workday.departments

**Source system:** Workday HCM — Supervisory Organization / Cost Center
**Grain:** one row per HR department / cost center
**Approx rows (demo scale):** 10
**Loaded by:** warehouse/generators/gen_raw_workday.py

## Business definition
NALA's HR org structure: Engineering, Product, Compliance, Operations, Finance, People, Marketing, Customer Support, Treasury, Data & Analytics — across London, Nairobi and Dakar. This is the *HR* department dimension, intentionally distinct from `raw_netsuite.departments` (no enforced cross-schema key).

## Known data-quality quirks
- `headcount` is a denormalized rollup that can drift from the actual employee count.
- `department_id` is a string ("DEPT-ENG"), unlike NetSuite's integer department ids.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| department_id | text | no | "DEPT-ENG" (PK) |
| name | text | no | department name |
| cost_center_code | text | no | "CC-1001" |
| parent_department_id | text | no | parent (sparse) |
| location | text | no | London / Nairobi / Dakar |
| headcount | integer | no | denormalized rollup (drifts) |
| is_active | boolean | no | active flag |

## Joins / lineage
- Referenced by `raw_workday.employees.department_id`.
