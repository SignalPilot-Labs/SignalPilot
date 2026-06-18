# raw_rafiki.fx_locks

**Source system:** Rafiki FX/pricing service
**Grain:** one row per locked FX quote
**Approx rows (demo scale):** ~thousands (601 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
FX rate locks merchants take to fix the rate used to price a payout for a short window.
A lock is consumed when a payout uses it; `consumed_by` references that payout.

## Known data-quality quirks
- `consumed_by` only set when `consumed = true`.
- Not every payout uses a lock; not every lock is consumed.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| fx_lock_id | text | no | PK, `fxl_<hex>` |
| merchant_id | text | no | Owning merchant |
| base_currency | text | no | USD/USDC/USDT/PYUSD |
| quote_currency | text | no | Local payout currency |
| rate | numeric | no | Locked rate |
| margin_bps | integer | no | Margin (bps) |
| amount_base | numeric | no | Locked base amount |
| expires_at | timestamptz | no | Lock expiry |
| consumed | boolean | no | Consumed flag |
| consumed_by | text | no | payout_id that consumed it |
| created_at | timestamptz | no | Lock creation time |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; `consumed_by` -> `payouts.payout_id`.
- `payouts.fx_lock_id` -> `fx_locks.fx_lock_id`.
