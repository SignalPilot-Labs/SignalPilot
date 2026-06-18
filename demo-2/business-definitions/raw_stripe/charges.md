# raw_stripe.charges

**Source system:** Stripe (Charges API)
**Grain:** one row per charge (a single card capture attempt on a payment intent)
**Approx rows (demo scale):** ~900k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
A Charge is the actual money movement off a NALA user's card to fund a transfer. Carries success/failure, refund/dispute flags, a denormalized card snapshot, and the linked balance transaction (settled funds + fees).

## Known data-quality quirks
- `created` is epoch **seconds**.
- `amount`/`amount_captured`/`amount_refunded` are MINOR units (cents).
- `status` includes legacy value `paid` (treat as succeeded).
- `failure_code`/`failure_message` only on non-success rows.
- Card brand/last4 denormalized here (Stripe embeds payment_method_details).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `ch_...` (PK) |
| created | bigint | no | epoch SECONDS |
| amount | bigint | no | MINOR units |
| amount_captured | bigint | no | MINOR units |
| amount_refunded | bigint | no | MINOR units |
| currency | text | no | lowercase ccy |
| status | text | no | succeeded/failed/pending + legacy 'paid' |
| paid / captured / refunded / disputed | boolean | no | state flags |
| customer | text | no | `cus_...` |
| payment_intent | text | no | `pi_...` |
| payment_method | text | no | `pm_...` |
| balance_transaction | text | no | `txn_...` |
| card_brand | text | yes | denormalized brand |
| card_last4 | text | yes | denormalized last4 |
| card_funding | text | no | credit/debit/prepaid |
| card_country | text | no | issuer country |
| receipt_email | text | yes | receipt email (dirty, sparse) |
| failure_code | text | no | sparse |
| failure_message | text | no | sparse |
| outcome_type | text | no | authorized/issuer_declined |
| risk_level | text | no | normal/elevated/highest |
| livemode | boolean | no | live vs test |
| metadata | jsonb | no | nala_customer_code |

## Joins / lineage
- `payment_intent` -> `raw_stripe.payment_intents.id`; `customer` -> `customers.id`.
- `balance_transaction` -> `raw_stripe.balance_transactions.id`.
