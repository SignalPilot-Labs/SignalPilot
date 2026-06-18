# raw_netsuite.departments

**Source system:** Oracle NetSuite — Department record
**Grain:** one row per department / cost center
**Approx rows (demo scale):** 9
**Loaded by:** warehouse/generators/gen_raw_netsuite.py

## Business definition
NetSuite departments used to dimensionalize GL postings and AP bills by function (Engineering, Compliance, Operations, etc.). This is the *finance* department dimension — distinct from `raw_workday.departments` (HR org), and there is intentionally NO enforced cross-schema key between them.

## Known data-quality quirks
- `subsidiary_id` and `parent_id` are sparse.
- Department ids here (integer internalIds) do not match Workday's string `DEPT-*` ids.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| department_id | bigint | no | NetSuite internalId (PK) |
| name | text | no | department name |
| parent_id | bigint | no | parent department (sparse) |
| subsidiary_id | bigint | no | owning subsidiary (sparse) |
| is_inactive | boolean | no | inactive flag |

## Joins / lineage
- Referenced (sparsely) by `gl_transactions.department_id` and `vendor_bills.department_id`.
