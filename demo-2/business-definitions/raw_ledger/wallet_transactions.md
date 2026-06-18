# raw_ledger.wallet_transactions

**Source system:** internal core ledger service
**Grain:** one row per credit/debit hitting a wallet balance
**Approx rows (demo scale):** a few per wallet
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
Movement log for each wallet, with a running `balance_after`. Mirrors customer-visible wallet activity and treasury moves. Most rows link to a journal entry via `entry_id`, but legacy rows are unlinked.

## Known data-quality quirks
- `entry_id` is ~10% null (legacy unlinked txns).
- `balance_after` ~8% null on old rows.
- `created` is a legacy duplicate of `occurred_at`, ~60% null.
- `reference_id` is ~30% null; when present, a transfer UUID.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| wallet_txn_id | bigint | no | PK |
| wallet_id | bigint | no | -> wallets.wallet_id |
| entry_id | bigint | no | -> journal_entries.entry_id (nullable) |
| txn_type | text | no | CREDIT / DEBIT |
| amount | numeric(20,4) | no | Positive magnitude |
| currency | text | no | Currency |
| balance_after | numeric(20,4) | no | Running balance (nullable on old rows) |
| reference_id | text | no | Transfer/settlement id (dirty join key) |
| description | text | no | Free text |
| occurred_at | timestamptz | no | When it happened |
| created | timestamptz | no | Legacy duplicate ts, mostly null |

## Joins / lineage
- `wallet_id` -> raw_ledger.wallets.
- `entry_id` -> raw_ledger.journal_entries (when not null).
