# raw_stripe.disputes

**Source system:** Stripe (Disputes / Chargebacks API)
**Grain:** one row per dispute (chargeback) raised against a charge
**Approx rows (demo scale):** ~11k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
A cardholder dispute / chargeback on a NALA funding charge. Tracks reason, lifecycle status, and the evidence deadline. Feeds fraud and chargeback-rate monitoring.

## Known data-quality quirks
- `created`/`evidence_due_by` are epoch **seconds**; `amount` MINOR units.
- ~1.2% of successful charges are disputed.
- `status` enum spans warning_needs_response -> won/lost.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `dp_...` (PK) |
| object | text | no | 'dispute' |
| created | bigint | no | epoch SECONDS |
| amount | bigint | no | MINOR units |
| currency | text | no | lowercase ccy |
| charge | text | no | `ch_...` |
| payment_intent | text | no | `pi_...` |
| balance_transaction | text | no | `txn_...` |
| reason | text | no | fraudulent/product_not_received/... |
| status | text | no | needs_response/under_review/won/lost |
| is_charge_refundable | boolean | no | |
| evidence_due_by | bigint | no | epoch s, sparse |
| metadata | jsonb | no | |

## Joins / lineage
- `charge` -> `raw_stripe.charges.id`.
