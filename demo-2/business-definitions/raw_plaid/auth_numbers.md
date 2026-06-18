# raw_plaid.auth_numbers

**Source system:** Plaid (Auth API)
**Grain:** one row per account's ACH/wire number set
**Approx rows (demo scale):** ~26k
**Loaded by:** warehouse/generators/gen_raw_plaid.py

## Business definition
The full account + routing numbers Plaid returns from the /auth product — what NALA uses to initiate ACH debits to fund transfers. **Heavy PII**: this is the only place full bank account numbers live.

## Known data-quality quirks
- `created_at` is an ISO-8601 **string**.
- US accounts use ABA routing + long account numbers; non-US use sort-code/IBAN-ish numbers and `account_type='international'`.
- `wire_routing` ~40% null (US only).
- Synthetic surrogate PK `id` (bigserial) — Plaid has no natural id here.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigserial | no | surrogate PK |
| account_id | text | no | -> accounts.account_id |
| item_id | text | no | -> items.item_id |
| routing | text | yes | ACH routing / sort code |
| account | text | yes | full bank account number |
| wire_routing | text | yes | wire routing, sparse |
| account_type | text | no | ach/eft/international |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `account_id` -> `raw_plaid.accounts.account_id`.
