# raw_sendgrid.events

**Source system:** Twilio SendGrid Event Webhook
**Grain:** one row per delivery/engagement event (fanned out from a message)
**Approx rows (demo scale):** ~8,000,000 (2–4 events per message)
**Loaded by:** warehouse/generators/gen_raw_sendgrid.py

## Business definition
The raw event stream behind email sends: `processed → delivered → open → click`, plus `bounce`, `dropped`, `spamreport`, `unsubscribe`. This is the source of truth for deliverability and engagement analytics (open/click rates, bounce reasons).

## Known data-quality quirks
- `timestamp` is epoch **seconds** (SendGrid native), NOT milliseconds and not a timestamptz.
- `email` is re-dirtied per event (the same recipient can appear with casing/space drift across its own events).
- Most engagement columns (`url`, `useragent`, `ip`, `reason`, `bounce_type`, `response`) are sparse and only set for the relevant event type.
- A message has many events; `delivered` only exists for delivered messages, `open`/`click` only for engaged ones.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| event_id | text | no | sg_event_id (PK) |
| sg_message_id | text | no | FK-ish to messages.sg_message_id |
| email | text | yes | recipient at event time (dirty) |
| event | text | no | processed/delivered/open/click/bounce/spamreport/dropped/unsubscribe |
| timestamp | bigint | no | epoch SECONDS |
| smtp_id | text | no | smtp message id (sparse) |
| category | text | no | message category (sparse) |
| url | text | no | clicked URL (click only) |
| useragent | text | no | client UA (open/click, PII-ish) |
| ip | inet | yes | engagement IP (open/click, sparse) |
| reason | text | no | bounce/drop reason (sparse) |
| bounce_type | text | no | blocked/bounce (sparse) |
| response | text | no | SMTP response (sparse) |
| customer_id | bigint | no | resolved canonical cid (sparse) |

## Joins / lineage
- Joins to `raw_sendgrid.messages` on `sg_message_id`.
- `customer_id` (when present) joins to the canonical customer.
