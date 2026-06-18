# raw_ledger.account_types

**Source system:** internal core ledger service
**Grain:** one row per chart-of-accounts type
**Approx rows (demo scale):** 5
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
The five canonical accounting categories (asset, liability, equity, revenue, expense) used to classify every ledger account and to determine each account's normal balance side. Reporting uses `normal_balance` to sign balances correctly.

## Known data-quality quirks
- Tiny static lookup; no quirks.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| account_type_id | integer | no | PK |
| code | text | no | ASSET / LIABILITY / EQUITY / REVENUE / EXPENSE |
| name | text | no | Display name |
| normal_balance | text | no | DEBIT or CREDIT — the side that increases this type |
| description | text | no | Free text |

## Joins / lineage
- Joined from `raw_ledger.accounts.account_type_id`.
