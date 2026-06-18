# raw_segment.tracks

**Source system:** Segment (Connections — analytics.js / mobile SDK → warehouse destination)
**Grain:** one row per `track` call (a single user action / product event)
**Approx rows (demo scale):** ~5,000,000 (`N["events"]`)
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
The raw product-event stream behind NALA's consumer app and web funnels. Every meaningful user action — opening the app, viewing a quote, starting/confirming/completing a transfer, submitting KYC, adding a recipient — fires a Segment `track` event with an event-specific `properties` payload. This is the primary behavioral fact for funnel, activation, and retention analytics.

## Known data-quality quirks
- `user_id` is NULL for ~30% of rows (anonymous, pre-`identify` traffic); only `anonymous_id` is always present.
- Segment multi-timestamp drift: `original_timestamp` (ISO-Z text) < `sent_at` < `received_at` < `loaded_at`; values differ by ms to minutes.
- `original_timestamp` is stored as a text ISO-Z string, not a timestamp.
- `event_text` occasionally drifts from `event` (legacy lowercase label, ~5%).
- `context_device_id` is NULL on web and ~10% null on mobile; `context_os_name` null on web.
- `loaded_at` ~8% null on older rows.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id (uuid-like). PK. |
| event | text | no | Event name ('Transfer Started', 'KYC Submitted', ...). |
| event_text | text | no | Human label; occasionally drifts from `event`. |
| anonymous_id | text | yes | Device/browser anon id; stable per customer; = amplitude device_id. |
| user_id | text | yes | Customer code CUS_...; NULL when anonymous. |
| properties | jsonb | maybe | Event payload (send_amount, corridor, receive_country, fee, ...). |
| context_ip | inet | yes | Client IP. |
| context_library_name | text | no | analytics-ios / analytics-android / analytics.js. |
| context_library_version | text | no | SDK version. |
| context_app_version | text | no | App build, e.g. '4.2.0'. |
| context_device_type | text | no | ios / android / web. |
| context_device_id | text | yes | Device identifier. |
| context_os_name | text | no | iOS / Android. |
| context_locale | text | no | en-GB, fr-FR, ... |
| context_timezone | text | no | IANA tz. |
| timestamp | timestamptz | no | Canonical event time. |
| original_timestamp | text | no | ISO-Z string as emitted by the SDK. |
| sent_at | timestamptz | no | When the SDK flushed. |
| received_at | timestamptz | no | When Segment received it (load watermark). |
| loaded_at | timestamptz | no | When the warehouse destination wrote the row. |

## Joins / lineage
- `user_id` → `raw_core_transfers.customers.customer_code` (dirty: NULL for anonymous traffic; needs identity stitching via `identifies`).
- `anonymous_id` → `raw_amplitude.events.device_id` (same device key across analytics vendors).
- Staging: `stg_segment__tracks`.
