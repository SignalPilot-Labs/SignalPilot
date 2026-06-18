# raw_core_transfers.saved_recipients

**Source system:** internal core product DB (Postgres) — LEGACY monolith table
**Grain:** one row per legacy saved beneficiary (only ~40% of recipients have one)
**Approx rows (demo scale):** ~48,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The deprecated, messy predecessor to `recipients`. A legacy near-duplicate kept around for historical lookups. Only about 40% of modern recipients have a corresponding legacy row, and formats are inconsistent. Prefer `recipients`; use this only for legacy reconciliation.

## Known data-quality quirks
- Legacy column names: `id` (pk), `user_id` (= customer_id), `name` (single free-text field, sometimes only a first name).
- `country` is dirty: sometimes ISO2, sometimes the full country name (Kenya, Nigeria, ...).
- `payment_type` has inconsistent casing/values: `MPESA`, `mpesa`, `MOMO`, `momo`, `BANK`, `bank`, `mobile_money`.
- `mobile` uses legacy local format (leading `0`, e.g. `0712...`), bank rows null.
- `created` and `updated` are epoch-milliseconds **bigint**, not timestamps.
- `deleted` is a legacy 0/1 **integer** soft-delete flag (~10% deleted), not boolean.
- `migrated_recipient_id` links to recipients but is often null (~50%).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | Legacy primary key |
| user_id | bigint | no | Legacy name for customer_id -> customers.customer_id |
| name | text | yes | Single free-text name (sometimes first name only) |
| country | text | no | ISO2 OR full country name (dirty) |
| currency | text | no | Receive currency |
| mobile | text | yes | Legacy MSISDN, local format (bank rows null) |
| acct_no | text | yes | Legacy account number (mobile rows null) |
| payment_type | text | no | Inconsistent casing: MPESA/mpesa/MOMO/momo/BANK/bank/mobile_money |
| created | bigint | no | Creation time as epoch milliseconds |
| updated | bigint | no | Update time as epoch milliseconds |
| deleted | integer | no | Legacy soft-delete flag 0/1 |
| migrated_recipient_id | bigint | no | -> recipients.recipient_id (often null) |

## Joins / lineage
- `user_id` -> customers.customer_id.
- `migrated_recipient_id` -> recipients.recipient_id (sparse link to the modern table).
