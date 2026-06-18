# raw_fx.corridor_pricing

**Source system:** NALA internal quote service config
**Grain:** one row per (send currency, receive country, payout method) corridor
**Approx rows (demo scale):** ~141
**Loaded by:** warehouse/generators/gen_raw_fx.py

## Business definition
Per-corridor pricing configuration the quote service reads to build a customer
quote: the fixed transfer fee (often $0 for mobile money, ~$0.99 for bank
payouts per the company profile), the FX margin in bps, promo state, and
send-amount limits (consumer daily limits up to 5,000). Drives the headline
"send X get Y" the app shows.

## Known data-quality quirks
- Legacy camelCase column `"isActive"` kept alongside snake_case columns (must be double-quoted in SQL).
- `send_country` is denormalized and ~25% NULL (messy backfill).
- Mobile-money methods are usually fee-free; ~10% of corridors carry a nominal charge regardless.
- Both `"isActive"` and `promo_active` exist; `"isActive"` gates whether the corridor is live.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| corridor_pricing_id | integer | no | PK. |
| send_currency | text | no | Debit currency. |
| send_country | text | no | Debit country (denormalized, often NULL). |
| receive_currency | text | no | Credit currency. |
| receive_country | text | no | Credit country (ISO-2). |
| payout_method | text | no | M-PESA / Bank / MTN MoMo / etc. |
| fixed_fee_amount | numeric(18,2) | no | Fixed transfer fee. |
| fixed_fee_ccy | text | no | Currency of the fixed fee. |
| fx_margin_bps | numeric(10,4) | no | Corridor FX margin in basis points. |
| promo_active | boolean | no | Promotional pricing flag. |
| min_send_amount | numeric(18,2) | no | Minimum send amount. |
| max_send_amount | numeric(18,2) | no | Maximum send amount. |
| isActive | boolean | no | Legacy camelCase: corridor live flag. |
| effective_from | date | no | Config effective date. |
| updated_at | timestamptz | no | Last update. |

## Joins / lineage
- `payout_method` values align with `common.RECEIVE_MARKETS` rails.
- Aligns with `raw_fx.pricing_margins` on send/receive currency.
- PII: none.
