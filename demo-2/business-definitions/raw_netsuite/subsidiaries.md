# raw_netsuite.subsidiaries

**Source system:** Oracle NetSuite — Subsidiary record (OneWorld)
**Grain:** one row per legal subsidiary / consolidation entity
**Approx rows (demo scale):** 8
**Loaded by:** warehouse/generators/gen_raw_netsuite.py

## Business definition
NALA's legal entity structure in NetSuite OneWorld: the UK holding company plus operating subsidiaries (UK, US, Kenya, Tanzania, Senegal, Nigeria) and a consolidation elimination entity. Drives multi-currency consolidation and which base currency a GL line/bill reports in.

## Known data-quality quirks
- `parent_id` is NULL for the top holding company.
- One row is an `is_elimination = true` consolidation entity (not a real operating company).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| subsidiary_id | bigint | no | NetSuite internalId (PK) |
| name | text | no | subsidiary name |
| legal_name | text | no | registered legal name |
| country | text | no | ISO2 |
| base_currency | text | no | reporting base currency |
| is_elimination | boolean | no | consolidation elim entity |
| parent_id | bigint | no | parent subsidiary (sparse) |
| fiscal_calendar | text | no | fiscal calendar name |
| is_inactive | boolean | no | inactive flag |

## Joins / lineage
- Referenced by `gl_transactions.subsidiary_id`, `vendor_bills.subsidiary_id`, `vendors.subsidiary_id`, `departments.subsidiary_id`.
