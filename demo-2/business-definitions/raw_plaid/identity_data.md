# raw_plaid.identity_data

**Source system:** Plaid (Identity API)
**Grain:** one row per linked account's identity record
**Approx rows (demo scale):** ~21k
**Loaded by:** warehouse/generators/gen_raw_plaid.py

## Business definition
The name/email/phone/address Plaid returns from the bank for a linked account — used by NALA to verify that the funding bank account belongs to the app user (identity resolution / KYC corroboration). **Heavy PII**.

## Known data-quality quirks
- `created_at` is an ISO-8601 **string**.
- `primary_email`/`primary_phone` carry casing/format drift; `region` ~50% null.
- `emails_json` holds all known emails as a jsonb array (semi-structured PII).
- Synthetic surrogate PK `id` (bigserial).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigserial | no | surrogate PK |
| account_id | text | no | -> accounts.account_id |
| item_id | text | no | -> items.item_id |
| nala_customer_code | text | no | CUS_00000123 join key |
| full_name | text | yes | name on account |
| primary_email | text | yes | email (dirty) |
| primary_phone | text | yes | phone (dirty) |
| street | text | yes | address |
| city | text | yes | city |
| region | text | yes | state/county, sparse |
| postal_code | text | yes | postcode |
| country | text | no | country |
| emails_json | jsonb | yes | all emails (semi-structured) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `account_id` -> `raw_plaid.accounts.account_id`; `nala_customer_code` -> customer_master().code.
