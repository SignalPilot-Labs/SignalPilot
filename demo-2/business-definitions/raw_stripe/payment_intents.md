# raw_stripe.payment_intents

**Source system:** Stripe (PaymentIntents API)
**Grain:** one row per payment intent (one attempt to collect funds to top up / fund a transfer)
**Approx rows (demo scale):** ~900k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
A PaymentIntent is the lifecycle object for collecting money from a NALA user's card to fund an outbound remittance. Status walks from creation to `succeeded` (or fails/cancels). `nala_transfer_id` ties the funding event to the transfer it pays for.

## Known data-quality quirks
- `created`/`canceled_at` are epoch **seconds**.
- `amount`/`amount_received` are MINOR units (cents).
- `currency` lowercase (gbp/usd/eur).
- `status` has many states incl. legacy `requires_capture`; not all map cleanly.
- `nala_transfer_id` ~30% null and occasionally UPPERCASE (dirty) — clean before joining.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `pi_...` (PK) |
| object | text | no | 'payment_intent' |
| created | bigint | no | epoch SECONDS |
| amount | bigint | no | requested amount, MINOR units |
| amount_received | bigint | no | captured amount, MINOR units |
| currency | text | no | lowercase ccy |
| status | text | no | succeeded/processing/canceled/... |
| customer | text | no | `cus_...` |
| payment_method | text | no | `pm_...` |
| latest_charge | text | no | `ch_...` |
| capture_method | text | no | automatic/manual |
| confirmation_method | text | no | automatic/manual |
| description | text | no | free text |
| statement_descriptor | text | no | descriptor |
| nala_transfer_id | text | no | uuid of funded transfer (dirty, sparse) |
| canceled_at | bigint | no | epoch s, sparse |
| cancellation_reason | text | no | sparse |
| metadata | jsonb | no | nala_customer_code |

## Joins / lineage
- `customer` -> `raw_stripe.customers.id`; `latest_charge` -> `raw_stripe.charges.id`.
- `nala_transfer_id` -> core `transfers.transfer_id` (lowercase the value first).
