# raw_segment.screens

**Source system:** Segment
**Grain:** one row per mobile `screen` call (an in-app screen view on iOS/Android)
**Approx rows (demo scale):** ~1,670,000
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Segment `screen` calls capturing in-app navigation on the NALA mobile apps (SendMoney, KYC, Recipients, Wallet, etc.). Used for mobile funnel analysis and screen-flow / drop-off studies. Screens are mobile-only; web users are not represented here.

## Known data-quality quirks
- Mobile-only: web customers are remapped to a mobile customer at generation, so `context_device_type` is always ios/android.
- `user_id` is NULL for ~25% of rows (anonymous in-app sessions).
- `context_device_id` is ~10% null even though mobile.
- `properties` jsonb is small ({name, tab}).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id (PK) |
| anonymous_id | text | yes | Device anonymous id (always present) |
| user_id | text | yes | `CUS_...` code; NULL ~25% (anonymous) |
| name | text | no | Screen name (SendMoney, KYC, Recipients, ...) |
| properties | jsonb | no | {name, tab} |
| context_app_version | text | no | App build |
| context_device_type | text | no | ios / android |
| context_device_id | text | yes | Device identifier (~10% null) |
| context_os_name | text | no | iOS / Android |
| timestamp | timestamptz | no | Screen view time |
| received_at | timestamptz | no | When Segment received (load watermark) |

## Joins / lineage
- `anonymous_id` → `raw_segment.identifies.anonymous_id` to resolve `user_id`.
- `anonymous_id` == `raw_amplitude.events.device_id` for cross-source stitching.
- `user_id` = customer code → `common.customer_master`.
