# raw_segment.identifies

**Source system:** Segment (Connections — `identify` calls)
**Grain:** one row per `identify` call (≈ one per customer, the moment anonymous traffic becomes known)
**Approx rows (demo scale):** ~60,000 (≈ `N["customers"]`)
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Binds an `anonymous_id` (device/browser) to a known `user_id` (customer code) and records the user traits known at sign-in. This is the linchpin for identity resolution: it lets anonymous `tracks`/`pages` events be stitched back to a real customer.

## Known data-quality quirks
- `email` is dirtied (~12% uppercased, dot drift, leading/trailing spaces) and ~6% null — clean before joining.
- `phone` drifts format (E.164 / 00-prefix / spaced) and is ~15% null.
- `loaded_at` ~8% null.
- A given customer may have one identify here even though they have many tracks rows.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id. PK. |
| anonymous_id | text | yes | Device/browser anon id (= tracks.anonymous_id). |
| user_id | text | yes | Customer code CUS_... (always present here). |
| traits | jsonb | yes | User traits blob (name, country, currency, ...). |
| email | text | yes | Denormalized email trait; dirty. |
| phone | text | yes | Denormalized phone trait; dirty format. |
| context_ip | inet | yes | Client IP. |
| context_app_version | text | no | App build. |
| context_device_type | text | no | ios / android / web. |
| timestamp | timestamptz | no | When identify fired. |
| received_at | timestamptz | no | Load watermark. |
| loaded_at | timestamptz | no | Warehouse write time. |

## Joins / lineage
- `user_id` → `raw_core_transfers.customers.customer_code`.
- `email` → other source emails after `lower(trim(...))` (identity resolution; dirty key).
- `anonymous_id` → `raw_segment.tracks.anonymous_id` (stitch anonymous events to a user).
- Staging: `stg_segment__identifies`.
