# raw_core_transfers.promo_redemptions

**Source system:** internal core product DB (Postgres)
**Grain:** one row per promo code redeemed on a transfer
**Approx rows (demo scale):** ~450,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
Records each time a customer applied a promo code to a transfer, with the promo type and discount granted. Generated only for transfers that carried a promo_code (~15% of transfers).

## Known data-quality quirks
- Exists only for transfers with a non-null promo_code; no standalone redemptions.
- `transfer_id` is always populated (every redemption is tied to a transfer).
- `discount_amount` is capped at the fee (min(fee, 0.99)).
- `redemption_id` is a generated surrogate serial assigned at load time.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| redemption_id | bigint | no | Primary key (surrogate serial) |
| customer_id | bigint | no | -> customers.customer_id |
| transfer_id | uuid | no | -> transfers.transfer_id |
| promo_code | text | no | Applied promo code |
| promo_type | text | no | first_transfer / fee_waiver / fx_boost |
| discount_amount | numeric(18,2) | no | Discount granted |
| discount_currency | text | no | Discount currency (= send currency) |
| redeemed_at | timestamptz | no | Redemption time |

## Joins / lineage
- `customer_id` -> customers.customer_id.
- `transfer_id` -> transfers.transfer_id; transfers.promo_code aligns with promo_code.
