# raw_amplitude.events

**Source system:** Amplitude
**Grain:** one row per Amplitude event
**Approx rows (demo scale):** ~3,500,000
**Loaded by:** warehouse/generators/gen_raw_amplitude.py

## Business definition
Amplitude product-analytics event stream (Export API / warehouse sync) covering sessions, sign-ups, KYC, quotes, and transfers. NALA dual-instruments many events through both Segment and Amplitude, so this overlaps `raw_segment.tracks`; Amplitude is the source for retention, session, and behavioral-cohort analysis.

## Known data-quality quirks
- `event_time`, `client_event_time`, `server_upload_time`, and `session_id` are **epoch milliseconds** stored as `bigint`, not timestamps — a deliberate format-drift trap requiring `to_timestamp(col/1000)`.
- `session_id` is epoch-ms of session start (and would be `-1` if no session).
- `user_id` is NULL for ~25% of rows (anonymous traffic).
- `idfa` is iOS-only and ~40% null due to ATT (App Tracking Transparency) denial; null on android/web.
- `adid` (GAID) is android-only and ~15% null; null on iOS/web.
- `device_id` ~5% null; `ip_address` ~6% null.
- `region` is populated with the city value (region ≈ city), not a true region.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| uuid | text | no | Amplitude event uuid (PK) |
| event_id | bigint | no | Per-user monotonic-ish event id |
| amplitude_id | bigint | yes | Amplitude internal user id (per-customer surrogate) |
| user_id | text | yes | `CUS_...` code; NULL for anonymous (~25%) |
| device_id | text | yes | Device id; maps to Segment `anonymous_id` (~5% null) |
| session_id | bigint | no | Epoch-ms of session start (-1 if none) |
| event_type | text | no | Event name (Transfer Completed, Session Start, ...) |
| event_time | bigint | no | EPOCH MS event time (format drift) |
| client_event_time | bigint | no | EPOCH MS client-reported time |
| server_upload_time | bigint | no | EPOCH MS server received (load watermark) |
| event_properties | jsonb | no | Event payload (receive_country, send_amount, revenue, ...) |
| user_properties | jsonb | yes | Snapshot of user props at event time (plan, country, kyc_status) |
| app_version | text | no | App build, e.g. `4.2.0` |
| platform | text | no | iOS / Android / Web |
| os_name | text | no | iOS / Android (null on web) |
| country | text | no | Country name |
| region | text | no | Region (≈ city value) |
| city | text | no | City |
| ip_address | inet | yes | Client IP (~6% null) |
| idfa | text | yes | iOS advertising id; ~40% null (ATT), null off-iOS |
| adid | text | yes | Android advertising id (GAID); ~15% null, null off-android |
| is_attribution_event | boolean | no | True on Transfer Completed events |

## Joins / lineage
- `user_id` = customer code → `common.customer_master` (NULL where anonymous).
- `device_id` == `raw_segment.tracks.anonymous_id` (== `det_uuid(("device", cid))`) — primary cross-source device key.
- `amplitude_id` → `raw_amplitude.user_properties.amplitude_id` (per-user profile snapshot).
- Overlaps `raw_segment.tracks` on the same user actions (dual-instrumented).
