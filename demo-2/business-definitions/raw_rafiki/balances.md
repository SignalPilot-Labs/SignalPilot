# raw_rafiki.balances

**Source system:** Rafiki ledger service
**Grain:** one row per merchant per currency (current snapshot)
**Approx rows (demo scale):** ~thousands (166 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Current per-merchant, per-currency balance held on the Rafiki platform — available,
pending and reserved amounts. A point-in-time snapshot (as of the build date),
complemented by the movement-level `balance_transactions`.

## Known data-quality quirks
- One row per (merchant, currency) where currency includes USD, the accepted stablecoins and the settlement currency.
- `as_of`/`updated_at` are pinned to the snapshot date.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| balance_id | text | no | PK |
| merchant_id | text | no | Owning merchant |
| currency | text | no | USD/USDC/local ccy |
| available_amount | numeric | no | Available balance |
| pending_amount | numeric | no | Pending balance |
| reserved_amount | numeric | no | Reserved balance |
| as_of | timestamptz | no | Snapshot time |
| updated_at | timestamptz | no | Last update |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`.
