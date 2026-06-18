# raw_core_transfers.customer_addresses

**Source system:** internal core product DB (Postgres)
**Grain:** one row per customer address (a customer may have 1-2)
**Approx rows (demo scale):** ~72,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
Postal addresses for sending customers, used for KYC / proof of address and billing. Most customers have one (home) address; ~20% have a second billing or proof_of_address row.

## Known data-quality quirks
- `created` is a legacy ISO **string** column (text), not a timestamptz — no timezone, requires casting.
- `line2` is sparse (~70% null).
- `verified` is true only ~70% of the time.
- No soft-delete column; rows persist.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| address_id | bigint | no | Primary key |
| customer_id | bigint | no | -> customers.customer_id |
| address_type | text | no | home / billing / proof_of_address |
| line1 | text | yes | Street address line 1 |
| line2 | text | yes | Address line 2 (sparse) |
| city | text | yes | City |
| postcode | text | yes | Postal code |
| country | text | no | Country |
| is_primary | boolean | no | Primary address flag (home = true) |
| verified | boolean | no | Address verified flag (~70% true) |
| created | text | no | Legacy ISO string timestamp (not tz) |

## Joins / lineage
- `customer_id` -> customers.customer_id.
