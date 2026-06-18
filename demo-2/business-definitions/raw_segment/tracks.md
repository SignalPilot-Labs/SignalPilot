# raw_segment.tracks

**Source system:** Segment
**Grain:** one row per `track` call (a single user action / product event)
**Approx rows (demo scale):** ~5,000,000
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Segment Connections event stream of product actions emitted by NALA's web and mobile clients (e.g. `Transfer Started`, `KYC Submitted`, `Quote Viewed`). This is the primary top-of-funnel behavioral fact for product and growth analytics, used to build funnels, conversion rates, and activation cohorts. NALA dual-instruments many of these events through Amplitude as well, so expect overlap with `raw_amplitude.events`.

## Known data-quality quirks
- Multiple near-equal timestamps with deliberate drift: `original_timestamp` (SDK) < `sent_at` < `received_at` < `loaded_at`. Use `timestamp` (tz) as the canonical event time.
- `original_timestamp` is an ISO-Z **text** string, not a timestamptz — must be cast before time math.
- `user_id` is NULL for ~30% of rows (pre-identify anonymous traffic); `anonymous_id` is always present.
- `context_device_id` is only populated on mobile (NULL on web) and is additionally ~10% null on mobile.
- `event_text` usually mirrors `event` but ~5% of rows carry a drifted lowercase legacy label.
- `loaded_at` is ~8% null; `context_ip` ~5% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id (PK, uuid-like) |
| event | text | no | Event name, e.g. `Transfer Started`, `KYC Submitted` |
| event_text | text | no | Human label; occasionally drifts from `event` |
| anonymous_id | text | yes | Device/browser anonymous id (always present); device key |
| user_id | text | yes | `CUS_...` customer code; NULL for anonymous traffic |
| properties | jsonb | no | Event-specific payload (send_amount, corridor, fee, error_code, etc.) |
| context_ip | inet | yes | Client IP address |
| context_library_name | text | no | SDK name (analytics-ios / analytics-android / analytics.js) |
| context_library_version | text | no | SDK version |
| context_app_version | text | no | App build, e.g. `4.2.0` |
| context_device_type | text | no | ios / android / web |
| context_device_id | text | yes | Device identifier (mobile only, often null) |
| context_os_name | text | no | iOS / Android |
| context_locale | text | no | Locale, e.g. en-GB, sw-KE |
| context_timezone | text | no | IANA tz, e.g. Europe/London |
| timestamp | timestamptz | no | Canonical event time (use this) |
| original_timestamp | text | no | ISO-Z string as emitted by the SDK (cast required) |
| sent_at | timestamptz | no | When the SDK flushed |
| received_at | timestamptz | no | When Segment received (load watermark) |
| loaded_at | timestamptz | no | When the warehouse destination wrote the row (~8% null) |

## Joins / lineage
- `user_id` = customer code → `common.customer_master` (NULL where anonymous).
- `anonymous_id` == `raw_amplitude.events.device_id` (== `det_uuid(("device", cid))`); the stable per-customer device key for cross-source identity resolution.
- `raw_segment.identifies` resolves `anonymous_id` → `user_id` (anonymous becomes known).
