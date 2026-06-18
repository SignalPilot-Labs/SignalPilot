# raw_segment.groups

**Source system:** Segment
**Grain:** one row per `group` call (associates a user with a merchant/org)
**Approx rows (demo scale):** ~1,200
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Sparse Segment `group` calls that associate a user with a merchant/organization on the Rafiki B2B side. Used to link consumer analytics identities to B2B merchant accounts for blended account-level reporting.

## Known data-quality quirks
- Very sparse table (≈ customers / 50).
- `anonymous_id` is ~20% null (unlike most Segment tables, where it is always present).
- `group_id` is a synthetic `org_<n>` merchant/org id, not a real merchant key.
- `traits` jsonb holds {name, plan, industry}.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id (PK) |
| anonymous_id | text | yes | Device anonymous id (~20% null) |
| user_id | text | yes | `CUS_...` customer code |
| group_id | text | no | Merchant / org id (e.g. `org_7`) |
| traits | jsonb | no | {name, plan, industry} |
| timestamp | timestamptz | no | Group call time |
| received_at | timestamptz | no | When Segment received (load watermark) |

## Joins / lineage
- `user_id` = customer code → `common.customer_master`.
- `group_id` → merchant/org dimension (synthetic `org_<n>` keys on the Rafiki B2B side).
