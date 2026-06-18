# raw_twilio.messages

**Source system:** Twilio Programmable Messaging (SMS) — Message resource + status-callback webhooks
**Grain:** one row per SMS message (mostly outbound OTP / notification / marketing)
**Approx rows (demo scale):** ~3,000,000 (sized off `N["transfers"]`)
**Loaded by:** warehouse/generators/gen_raw_twilio.py

## Business definition
Every transactional SMS NALA sends to a customer — one-time passcodes for login/verification, transfer status notifications, and occasional marketing blasts. Each row carries Twilio's delivery lifecycle (`status`) and cost (`price`). Used to measure deliverability, SMS spend by message type, and OTP funnel friction.

## Known data-quality quirks
- `to_number` is a customer phone run through `dirty_phone` — format drifts (E.164, `00`-prefix, spaces, no `+`). Needs normalization to join.
- Timestamps (`date_created`, `date_sent`, `date_updated`) are RFC2822 strings, not timestamptz. `date_sent` is NULL when `status = 'queued'`.
- `price` is a signed string in USD (e.g. `-0.0075`) and NULL while queued.
- `customer_id` resolved for ~90% of rows; ~10% NULL (unresolved identity).
- `messaging_service_sid` sparse (~40% populated); `error_code`/`error_message` only on undelivered/failed.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| message_sid | text | no | Twilio `SM...` message SID (PK) |
| account_sid | text | no | Twilio `AC...` account SID |
| messaging_service_sid | text | no | Twilio `MG...` messaging service (sparse) |
| to_number | text | yes | Recipient phone, dirty E.164 drift |
| from_number | text | no | NALA sender id / shortcode |
| body | text | no | Message text (OTP code embedded) |
| num_segments | integer | no | SMS segment count |
| num_media | integer | no | MMS media count (0 for SMS) |
| direction | text | no | outbound-api / inbound |
| message_type | text | no | otp / notification / marketing |
| status | text | no | queued/sent/delivered/undelivered/failed |
| error_code | integer | no | Twilio error code (sparse) |
| error_message | text | no | error description (sparse) |
| price | text | no | signed USD cost string (sparse) |
| price_unit | text | no | currency of price (USD) |
| customer_id | bigint | no | resolved canonical cid (~10% NULL) |
| date_created | text | no | RFC2822 string |
| date_sent | text | no | RFC2822 string (NULL if queued) |
| date_updated | text | no | RFC2822 string |
| api_version | text | no | legacy "2010-04-01" |
| raw_payload | jsonb | no | vendor webhook blob |

## Joins / lineage
- Joins to the canonical customer on `customer_id` (clean), or on normalized `to_number` ↔ `customer_master.phone` (dirty — strip spaces, normalize `00`→`+`).
