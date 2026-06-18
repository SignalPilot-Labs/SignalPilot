# raw_braze.messages_sent

**Source system:** Braze Currents (event export stream)
**Grain:** one row per message event (a send/delivery/open/click/... event)
**Approx rows (demo scale):** ~360,000 (N["customers"] × 6)
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
The core engagement fact for marketing/CRM: every message NALA dispatches to a
customer and its downstream event (sent → delivered → open → click). Joins to
the canonical customer via `external_user_id` (customer code) and a dirty
`email`. Used for channel performance, deliverability and engagement funnels.

## Known data-quality quirks
- `sent_at` is an ISO-Z **text** string; `time` is the same instant as **epoch seconds** (duplicate, format drift).
- `email` is dirty (casing/space/typo drift via `dirty_email`) and ~5% NULL on email rows; always NULL for push/sms/in_app rows.
- Exactly one of `campaign_id` / `canvas_id` is populated per row.
- `event_type` is a funnel — most rows are `sent`/`delivered`, few `open`/`click`/`bounce`.
- `external_user_id` is the NALA customer code `CUS_XXXXXXXX` (cross-source join key).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate PK |
| dispatch_id | text | no | 24-hex; groups one send |
| campaign_id | text | no | → campaigns.campaign_id (nullable) |
| canvas_id | text | no | → canvases.canvas_id (nullable) |
| external_user_id | text | no | NALA customer code (join key) |
| user_id | text | no | Braze internal user id (24-hex) |
| email | text | **yes** | recipient email, dirty, sparse |
| channel | text | no | email / push / sms / in_app_message |
| message_variation | text | no | A / B / control |
| event_type | text | no | sent / delivered / open / click / bounce / unsubscribe |
| sent_at | text | no | ISO-Z string |
| time | bigint | no | epoch seconds (duplicate of sent_at) |
| is_amp | boolean | no | AMP email flag |
| metadata | jsonb | no | vendor payload, sparse |

## Joins / lineage
- `campaign_id` → `raw_braze.campaigns`; `canvas_id` → `raw_braze.canvases`.
- `external_user_id` → NALA customer code (also in raw_zendesk.users.external_id, raw_intercom.conversations.contact_external_id). Key is clean; `email` needs cleaning.
