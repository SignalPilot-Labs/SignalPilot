# raw_rafiki.rate_cards

**Source system:** Rafiki internal platform DB (pricing service)
**Grain:** one row per merchant pricing version (effective-date range)
**Approx rows (demo scale):** ~2,400 (76 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Pricing applied to a merchant's collections, payouts and FX. Versioned via
`effective_from`/`effective_to`; `is_current` flags the live card. Fees in basis
points plus an optional flat USD fee and minimum payout.

## Known data-quality quirks
- SCD-lite: only one row per merchant has `is_current = true`; `effective_to` null on it.
- Multiple historical cards per merchant.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| rate_card_id | text | no | PK |
| merchant_id | text | no | Owning merchant |
| name | text | no | Card name |
| collection_fee_bps | integer | no | Collection fee (bps) |
| payout_fee_bps | integer | no | Payout fee (bps) |
| fx_margin_bps | integer | no | FX margin (bps) |
| flat_fee_usd | numeric | no | Flat per-txn fee |
| min_payout_usd | numeric | no | Minimum payout |
| effective_from | date | no | Start of validity |
| effective_to | date | no | End of validity (null = current) |
| is_current | boolean | no | Live card flag |
| created_at | timestamptz | no | Creation time |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; referenced by `collections.rate_card_id`.
