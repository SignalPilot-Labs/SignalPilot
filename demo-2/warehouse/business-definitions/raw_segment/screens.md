# raw_segment.screens

**Source system:** Segment (Connections — `screen` calls, mobile)
**Grain:** one row per mobile in-app `screen` view
**Approx rows (demo scale):** ~1,666,000 (`N["events"]` / 3)
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Mobile in-app navigation events (iOS/Android): which screens users land on (SendMoney, QuoteReview, KYC, Recipients, Wallet, ...). Feeds in-app funnel and screen-flow analysis.

## Known data-quality quirks
- Mobile-only by construction; no web rows.
- `user_id` NULL for ~25% of rows (anonymous in-app sessions).
- `context_device_id` ~10% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id. PK. |
| anonymous_id | text | yes | Device anon id. |
| user_id | text | yes | Customer code CUS_...; ~25% NULL. |
| name | text | no | Screen name ('SendMoney', 'KYC', ...). |
| properties | jsonb | no | {name, tab}. |
| context_app_version | text | no | App build. |
| context_device_type | text | no | ios / android. |
| context_device_id | text | yes | Device identifier. |
| context_os_name | text | no | iOS / Android. |
| timestamp | timestamptz | no | Event time. |
| received_at | timestamptz | no | Load watermark. |

## Joins / lineage
- `anonymous_id` → `raw_segment.identifies.anonymous_id`.
- `user_id` → `raw_core_transfers.customers.customer_code`.
- No staging model (low-priority table).
