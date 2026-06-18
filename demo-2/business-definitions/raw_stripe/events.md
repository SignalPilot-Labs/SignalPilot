# raw_stripe.events

**Source system:** Stripe (Events / Webhooks API)
**Grain:** one row per Stripe event (webhook notification of an object change)
**Approx rows (demo scale):** ~1.8M
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
The Stripe event stream NALA ingests via webhooks — `payment_intent.created`, `charge.succeeded`, `charge.failed`, etc. Used for near-real-time funding-status updates and as an audit trail.

## Known data-quality quirks
- `created` is epoch **seconds**.
- `api_version` drifts across legacy values (different Stripe API pins over time).
- `request_id` ~20% null; `data` is the raw event payload jsonb.
- High volume (~2 events per payment intent).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `evt_...` (PK) |
| object | text | no | 'event' |
| created | bigint | no | epoch SECONDS |
| type | text | no | e.g. charge.succeeded |
| api_version | text | no | legacy Stripe API date |
| livemode | boolean | no | live vs test |
| request_id | text | no | `req_...` sparse |
| object_id | text | no | id of the object in data.object |
| data | jsonb | no | raw event payload |

## Joins / lineage
- `object_id` -> `raw_stripe.payment_intents.id` / `charges.id` depending on `type`.
