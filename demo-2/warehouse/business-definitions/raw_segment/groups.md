# raw_segment.groups

**Source system:** Segment (Connections — `group` calls)
**Grain:** one row per `group` association (user ↔ merchant/org)
**Approx rows (demo scale):** ~1,200 (`N["customers"]` / 50)
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Associates a user with a group — used on the analytics side to tie individuals to Rafiki B2B merchant/org accounts. Sparse; only populated where a user belongs to an org.

## Known data-quality quirks
- `anonymous_id` ~20% null.
- Low volume; not all customers appear.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id. PK. |
| anonymous_id | text | yes | Device anon id; ~20% null. |
| user_id | text | yes | Customer code CUS_... |
| group_id | text | no | Merchant / org id ('org_123'). |
| traits | jsonb | no | {name, plan, industry}. |
| timestamp | timestamptz | no | Event time. |
| received_at | timestamptz | no | Load watermark. |

## Joins / lineage
- `user_id` → `raw_core_transfers.customers.customer_code`.
- `group_id` → Rafiki merchant id (loose, analytics-side label).
- No staging model (low-priority table).
