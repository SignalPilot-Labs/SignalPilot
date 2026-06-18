# raw_ledger.reconciliation_breaks

**Source system:** internal core ledger service (recon job)
**Grain:** one row per discrepancy found in a reconciliation run
**Approx rows (demo scale):** ~140 (test)
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
A break is a difference between the internal ledger balance and an external balance for an account at a point in time. `break_amount = ledger_balance - external_balance`. Breaks are triaged (OPEN -> INVESTIGATING -> RESOLVED) and categorized by likely cause.

## Known data-quality quirks
- `account_id` is nullable (some breaks are aggregate / unattributed).
- `resolved_at` set only for RESOLVED breaks.
- `notes` ~50% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| break_id | bigint | no | PK |
| run_id | bigint | no | -> reconciliation_runs.run_id |
| account_id | bigint | no | -> accounts.account_id (nullable) |
| currency | text | no | Currency |
| ledger_balance | numeric(20,4) | no | Internal ledger balance |
| external_balance | numeric(20,4) | no | External source balance |
| break_amount | numeric(20,4) | no | ledger - external |
| break_type | text | no | TIMING / MISSING_TXN / FX / UNKNOWN |
| status | text | no | OPEN / INVESTIGATING / RESOLVED |
| resolved_at | timestamptz | no | When resolved |
| notes | text | no | Free text, often null |

## Joins / lineage
- `run_id` -> raw_ledger.reconciliation_runs.
- `account_id` -> raw_ledger.accounts.
