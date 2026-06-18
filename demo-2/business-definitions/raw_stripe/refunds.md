# raw_stripe.refunds

**Source system:** Stripe (Refunds API)
**Grain:** one row per refund issued against a charge
**Approx rows (demo scale):** ~45k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
Money returned to a NALA user's card after a funding charge — typically when a transfer is canceled or fails downstream. Each refund references its originating charge and a negative balance transaction.

## Known data-quality quirks
- `created` is epoch **seconds**; `amount` in MINOR units.
- Only ~5% of successful charges have refunds.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `re_...` (PK) |
| object | text | no | 'refund' |
| created | bigint | no | epoch SECONDS |
| amount | bigint | no | MINOR units |
| currency | text | no | lowercase ccy |
| charge | text | no | `ch_...` |
| payment_intent | text | no | `pi_...` |
| balance_transaction | text | no | `txn_...` (negative) |
| reason | text | no | requested_by_customer/duplicate/fraudulent |
| status | text | no | succeeded/pending/failed/canceled |
| receipt_number | text | no | receipt id |
| metadata | jsonb | no | |

## Joins / lineage
- `charge` -> `raw_stripe.charges.id`; `balance_transaction` -> `balance_transactions.id`.
