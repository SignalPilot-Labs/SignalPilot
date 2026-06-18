# raw_core_transfers.transfer_fees

**Source system:** internal core product DB (Postgres)
**Grain:** one row per fee component of a transfer
**Approx rows (demo scale):** ~7,000,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The itemized fee breakdown for each transfer. Every transfer has a `transfer` fee and an `fx_margin` fee; transfers with a promo also get a `promo_discount` row. Sums to the total revenue/cost recognized on a transfer.

## Known data-quality quirks
- `amount` is **negative** for `promo_discount` rows (a discount), positive otherwise.
- A zero `transfer` fee is flagged with `is_waived = true`.
- Row count per transfer is 2 (no promo) or 3 (with promo); promo rows exist only when the transfer had a promo_code.
- `fee_id` is a generated surrogate serial assigned at load time.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| fee_id | bigint | no | Primary key (surrogate serial) |
| transfer_id | uuid | no | -> transfers.transfer_id |
| fee_type | text | no | transfer / fx_margin / promo_discount |
| amount | numeric(18,2) | no | Fee amount (negative for discounts) |
| currency | text | no | Fee currency (= send currency) |
| is_waived | boolean | no | Waived flag (true for zero/discount) |
| description | text | no | Human-readable fee description |
| created_at | timestamptz | no | Creation time (= transfer created_at) |

## Joins / lineage
- `transfer_id` -> transfers.transfer_id (child table).
