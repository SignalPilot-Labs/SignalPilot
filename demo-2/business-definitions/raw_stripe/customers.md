# raw_stripe.customers

**Source system:** Stripe (Customers API)
**Grain:** one row per Stripe Customer object (one NALA app user's card-funding identity)
**Approx rows (demo scale):** ~33k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
Each Stripe Customer represents a NALA consumer-app user as Stripe knows them — used to attach saved cards and run card/debit charges that FUND the user's outbound transfers. `nala_customer_code` maps back to the canonical NALA customer (`CUS_00000123`).

## Known data-quality quirks
- `created`/`deleted_at` are epoch **seconds** (bigint), not timestamps.
- ~6% null `email`; email casing/dot/space drift via dirty_email.
- ~15% null `phone`.
- `deleted` soft-delete flag; `deleted_at` only populated when deleted (~3%).
- `default_source` is a legacy/deprecated card pointer (~50% null).
- `currency` is lowercase Stripe presentment code (gbp/usd/eur).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Stripe id `cus_...` (PK) |
| object | text | no | always 'customer' |
| created | bigint | no | creation epoch SECONDS |
| email | text | yes | customer email (dirty) |
| name | text | yes | full name |
| phone | text | yes | phone (dirty, sparse) |
| description | text | no | free text |
| currency | text | no | default presentment ccy (lowercase) |
| delinquent | boolean | no | has unpaid invoices |
| livemode | boolean | no | live vs test |
| nala_customer_code | text | no | CUS_00000123 cross-source join key |
| default_source | text | no | legacy card id (deprecated) |
| invoice_prefix | text | no | invoice number prefix |
| deleted | boolean | no | soft delete flag |
| deleted_at | bigint | no | epoch s, only if deleted |
| metadata | jsonb | no | includes nala_cid, platform |

## Joins / lineage
- Joins to NALA core customers on `nala_customer_code` -> `common.customer_master().code`.
- Referenced by `raw_stripe.charges.customer` / `payment_intents.customer` / `payment_methods.customer` on `id`.
