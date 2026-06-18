# raw_braze.messages_sent

**Source system:** Braze
**Grain:** one row per message send event (Currents-style event stream)
**Approx rows (demo scale):** ~360,000 (customers × 6)
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
The Braze fact table: a Currents-style event stream with one row per outbound message event delivered to a NALA customer across email, push, SMS, and in-app channels. Each row records the channel, A/B variation, and funnel event type (sent / delivered / open / click / bounce / unsubscribe). This is the primary source for CRM engagement, deliverability, and campaign/canvas performance analysis.

## Known data-quality quirks
- `sent_at` is ISO-8601 text with a `Z` suffix; the duplicate `"time"` column is the same instant as **epoch seconds** (bigint). This drifts against `raw_braze.custom_events."time"`, which is **epoch milliseconds** — never mix the two without unit-aware conversion.
- Exactly one of `campaign_id` / `canvas_id` is populated per row; ~35% of sends come from a canvas (campaign_id null), the rest from a campaign (canvas_id null).
- `email` is PII and dirty (whitespace/case/typo noise from `dirty_email`); it is null for non-email channels (push/sms/in_app) and additionally null ~5% of the time on email rows.
- `event_type` is funnel-weighted (mostly sent/delivered), so opens/clicks/bounces are comparatively rare.
- `metadata` is null ~70% of the time.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate row id, primary key |
| dispatch_id | text | no | 24-hex id grouping a single send |
| campaign_id | text | no | -> raw_braze.campaigns.campaign_id; null when canvas-sourced |
| canvas_id | text | no | -> raw_braze.canvases.canvas_id; null when campaign-sourced |
| external_user_id | text | no | NALA customer code 'CUS_XXXXXXXX' |
| user_id | text | no | Braze-internal user id (24-hex) |
| email | text | yes | recipient email, dirty; null for non-email channels and ~5% of email rows |
| channel | text | no | email / push / sms / in_app_message |
| message_variation | text | no | A / B / control |
| event_type | text | no | sent / delivered / open / click / bounce / unsubscribe |
| sent_at | text | no | ISO-Z string (Currents 'time') |
| time | bigint | no | epoch SECONDS duplicate of sent_at |
| is_amp | boolean | no | AMP email flag (email rows only) |
| metadata | jsonb | no | vendor blob, e.g. {"variation_name": "v1"}; nullable |

## Joins / lineage
- `external_user_id` = NALA customer code (`CUS_...`), the canonical customer join key.
- `email` = dirty customer email — a fuzzy secondary join key into the customer master.
- `campaign_id` -> `raw_braze.campaigns.campaign_id`; `canvas_id` -> `raw_braze.canvases.canvas_id`.
