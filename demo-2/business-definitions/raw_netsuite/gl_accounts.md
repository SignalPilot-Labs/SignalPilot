# raw_netsuite.gl_accounts

**Source system:** Oracle NetSuite — Account record (chart of accounts)
**Grain:** one row per GL account
**Approx rows (demo scale):** 21
**Loaded by:** warehouse/generators/gen_raw_netsuite.py

## Business definition
NALA's chart of accounts: cash and stablecoin accounts, customer-funds-held / payable clearing accounts, revenue (FX margin, transfer fees, Rafiki), and expense accounts (payout costs, salaries, infra, compliance, marketing). Used to classify every GL line by account type/category.

## Known data-quality quirks
- `currency` is sparse (multi-currency accounts only).
- `account_type` uses NetSuite's internal enum values (Bank, AcctRec, AcctPay, COGS, OthCurrAsset…); `account_category` is a simplified asset/liability/equity/income/expense roll-up.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| account_id | bigint | no | NetSuite internalId (PK) |
| acctnumber | text | no | account number ("1000", "4000") |
| account_name | text | no | account name |
| account_type | text | no | NetSuite account type enum |
| account_category | text | no | asset/liability/equity/income/expense |
| parent_id | bigint | no | parent account (sparse) |
| currency | text | no | account currency (sparse) |
| is_summary | boolean | no | summary (rollup) account |
| is_inactive | boolean | no | inactive flag |
| created_at | timestamptz | no | account creation |

## Joins / lineage
- Referenced by `gl_transactions.account_id`.
