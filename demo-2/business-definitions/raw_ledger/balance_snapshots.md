# raw_ledger.balance_snapshots

**Source system:** internal core ledger service (reporting snapshot job)
**Grain:** one row per GL account per snapshot date (monthly)
**Approx rows (demo scale):** ~17 accounts x 18 months
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
Denormalized period-end balance snapshots per GL account, used for fast reporting without re-aggregating journal_lines. `balance` is signed per the account's normal balance.

## Known data-quality quirks
- Snapshots cover only GL accounts (not per-customer accounts) and only the last ~18 months.
- Balances are point-in-time and not guaranteed to tie to a journal_lines re-aggregation (snapshot drift is realistic).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| snapshot_id | bigint | no | PK |
| account_id | bigint | no | -> accounts.account_id |
| snapshot_date | date | no | Period end |
| currency | text | no | Account currency |
| debit_total | numeric(20,4) | no | Period debit total |
| credit_total | numeric(20,4) | no | Period credit total |
| balance | numeric(20,4) | no | Signed balance |
| created_at | timestamptz | no | When snapshot was written |

## Joins / lineage
- `account_id` -> raw_ledger.accounts.
