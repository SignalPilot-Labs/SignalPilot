# raw_flutterwave.balances

**Source system:** Flutterwave v3 API (/balances)
**Grain:** one row per (currency, snapshot) treasury balance
**Approx rows (demo scale):** ~6k+
**Loaded by:** warehouse/generators/gen_raw_flutterwave.py

## Business definition
Periodic snapshots of NALA's Flutterwave wallet/float balances per currency.
Used to monitor payout liquidity across receive markets.

## Known data-quality quirks
- `snapshot_at` is epoch **seconds** (bigint), not a timestamp.
- One row per currency per snapshot day (every ~2 days); `ledger_balance >= available_balance`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| balance_id | bigint | no | PK (synthetic) |
| currency | text | no | balance currency |
| available_balance | numeric(18,2) | no | spendable float |
| ledger_balance | numeric(18,2) | no | total incl. pending |
| snapshot_at | bigint | no | epoch **seconds** |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- Standalone treasury table.
