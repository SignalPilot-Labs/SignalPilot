# raw_core_transfers.cancellation_reasons

**Source system:** internal core product DB (Postgres)
**Grain:** one row per cancellation reason code
**Approx rows (demo scale):** 9
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
A small static lookup of the reasons a transfer can be cancelled, categorized by who/what triggered it (user, compliance, partner, system) and whether the reason is shown to the customer.

## Known data-quality quirks
- Fixed set of 9 reasons; `reason_id` is 1-based and stable.
- Some reasons are not user-facing (`is_user_facing = false`): COMPLIANCE_HOLD, DUPLICATE_TRANSFER, FRAUD_SUSPECTED.
- No timestamps or soft-delete; purely reference data.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| reason_id | bigint | no | Primary key |
| reason_code | text | no | e.g. COMPLIANCE_HOLD, USER_CANCELLED |
| reason_label | text | no | Human-readable label |
| category | text | no | compliance / user / partner / system |
| is_user_facing | boolean | no | Whether shown to the customer |

## Joins / lineage
- `reason_id` is referenced by transfers.cancellation_reason_id.
