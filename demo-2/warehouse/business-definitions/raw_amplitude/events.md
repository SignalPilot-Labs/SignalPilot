# raw_amplitude.events

**Source system:** Amplitude (Export API / warehouse sync)
**Grain:** one row per Amplitude event
**Approx rows (demo scale):** ~3,500,000 (`N["events"]` × 0.7)
**Loaded by:** warehouse/generators/gen_raw_amplitude.py

## Business definition
The Amplitude-side product-event stream. NALA dual-instruments key events through both Segment and Amplitude, so this overlaps `raw_segment.tracks` (same actions, different vendor shape). Used for Amplitude-native funnels, retention, and cohort analysis.

## Known data-quality quirks
- **`event_time`, `client_event_time`, `server_upload_time` are EPOCH MILLISECONDS (bigint)** — must divide by 1000 before `to_timestamp`. Classic vendor format-drift trap.
- `user_id` is NULL for ~25% of rows (anonymous); `device_id` is the fallback key.
- `session_id` is the epoch-ms of session start, or `-1` when there is no session.
- `idfa` is NULL ~40% of the time on iOS (ATT denial) and always null off-iOS; `adid` only on Android.
- `ip_address` ~6% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| uuid | text | no | Amplitude event uuid. PK. |
| event_id | bigint | no | Per-user monotonic event id. |
| amplitude_id | bigint | no | Amplitude internal user id. |
| user_id | text | yes | Customer code CUS_...; NULL when anonymous. |
| device_id | text | yes | Device id (= segment anonymous_id). |
| session_id | bigint | no | Epoch-ms session start, or -1. |
| event_type | text | no | Event name ('Transfer Completed', 'Session Start'). |
| event_time | bigint | no | **Epoch MS** event time. |
| client_event_time | bigint | no | **Epoch MS** client time. |
| server_upload_time | bigint | no | **Epoch MS** server received (watermark). |
| event_properties | jsonb | maybe | Event payload. |
| user_properties | jsonb | maybe | User-prop snapshot at event time. |
| app_version | text | no | '4.2.0'. |
| platform | text | no | iOS / Android / Web. |
| os_name | text | no | iOS / Android. |
| country / region / city | text | no | Geo. |
| ip_address | inet | yes | Client IP. |
| idfa | text | yes | iOS advertising id; ~40% null (ATT). |
| adid | text | yes | Android GAID. |
| is_attribution_event | boolean | no | True for attributable conversion events. |

## Joins / lineage
- `user_id` → `raw_core_transfers.customers.customer_code`.
- `device_id` → `raw_segment.tracks.anonymous_id`.
- Staging: `stg_amplitude__events` (converts epoch-ms to timestamptz).
