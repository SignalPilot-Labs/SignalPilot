# raw_stripe.payment_methods

**Source system:** Stripe (PaymentMethods API)
**Grain:** one row per saved payment method (card / bank / link) on a Stripe customer
**Approx rows (demo scale):** ~40k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
The cards/bank instruments NALA users have saved in Stripe to fund transfers. Card metadata (brand, last4, BIN, funding type) drives risk and fee logic. NALA stores last4 + BIN only — never the full PAN.

## Known data-quality quirks
- `created` is epoch **seconds**.
- ~90% are `type='card'`; remainder `us_bank_account` / `link` (card_* columns null).
- `card_bin` is a fixed 6-digit issuer prefix per brand (synthetic).
- ~50% null `billing_email`; email drift applied.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `pm_...` (PK) |
| object | text | no | 'payment_method' |
| created | bigint | no | epoch SECONDS |
| customer | text | no | `cus_...` owner |
| type | text | no | card / us_bank_account / link |
| card_brand | text | yes | visa/mastercard/amex/discover |
| card_last4 | text | yes | last 4 of PAN |
| card_bin | text | yes | issuer identification number (6 digit) |
| card_exp_month | integer | no | expiry month |
| card_exp_year | integer | no | expiry year |
| card_funding | text | no | credit/debit/prepaid |
| card_country | text | no | issuer country |
| card_fingerprint | text | yes | dedupe token |
| billing_email | text | yes | billing email (dirty, sparse) |
| livemode | boolean | no | live vs test |
| metadata | jsonb | no | nala_customer_code |

## Joins / lineage
- `customer` -> `raw_stripe.customers.id`.
- `id` referenced by `raw_stripe.charges.payment_method` / `payment_intents.payment_method`.
