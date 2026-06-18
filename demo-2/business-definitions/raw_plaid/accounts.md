# raw_plaid.accounts

**Source system:** Plaid (Accounts API)
**Grain:** one row per bank account exposed under a Plaid Item
**Approx rows (demo scale):** ~26k
**Loaded by:** warehouse/generators/gen_raw_plaid.py

## Business definition
The individual depository accounts (checking/savings) under a user's linked institution. Balances are used for fundability checks before pulling ACH funds for a transfer.

## Known data-quality quirks
- `created_at` is an ISO-8601 **string**.
- Balances are MAJOR units (numeric); `available_balance` ~15% null.
- `mask` is the account last4 (PII).
- `verification_status` includes `verification_expired`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| account_id | text | no | opaque (PK) |
| item_id | text | no | -> items.item_id |
| name | text | no | account name |
| official_name | text | no | sparse |
| mask | text | yes | account last 4 |
| type | text | no | depository |
| subtype | text | no | checking/savings |
| available_balance | numeric(18,2) | no | MAJOR units, sparse |
| current_balance | numeric(18,2) | no | MAJOR units |
| iso_currency_code | text | no | GBP/USD/EUR |
| verification_status | text | no | auto/manual verification state |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `item_id` -> `raw_plaid.items.item_id`.
- `account_id` referenced by `auth_numbers`, `transactions`, `identity_data`.
