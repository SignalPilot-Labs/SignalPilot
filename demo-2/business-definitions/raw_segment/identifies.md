# raw_segment.identifies

**Source system:** Segment
**Grain:** one row per `identify` call (roughly one per customer, at first sign-in)
**Approx rows (demo scale):** ~60,000
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Segment `identify` calls that tie an `anonymous_id` to a `user_id` and carry user traits — the moment anonymous traffic becomes a known customer. This is the backbone of identity resolution: it stitches pre-login behavioral events to a customer code and supplies denormalized profile traits (email, name, country, plan).

## Known data-quality quirks
- `email` and `phone` are denormalized traits and are deliberately dirty: `email` is mangled ~6% of rows, `phone` mangled/null ~15%.
- `email` is ~6% null and `phone` ~15% null after dirtying.
- `loaded_at` ~8% null; `context_ip` ~5% null.
- `traits` jsonb contains PII (email, name, country) duplicating the flat columns.
- One identify per customer (deduped on customer id), so this is effectively a per-customer table despite being an event call.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id (PK) |
| anonymous_id | text | yes | Device/browser anonymous id (always present) |
| user_id | text | yes | `CUS_...` customer code (always present on identify) |
| traits | jsonb | yes | {email, name, first_name, country, currency, plan, created_at} |
| email | text | yes | Denormalized email trait (dirty, ~6% null) |
| phone | text | yes | Denormalized phone trait (dirty, ~15% null) |
| context_ip | inet | yes | Client IP (~5% null) |
| context_app_version | text | no | App build |
| context_device_type | text | no | ios / android / web |
| timestamp | timestamptz | no | Identify time (~ first sign-in) |
| received_at | timestamptz | no | When Segment received (load watermark) |
| loaded_at | timestamptz | no | Warehouse write time (~8% null) |

## Joins / lineage
- `user_id` = customer code → `common.customer_master`.
- `anonymous_id` → `raw_segment.tracks.anonymous_id` / `raw_segment.pages` / `raw_segment.screens` to back-fill `user_id` onto anonymous events.
- `anonymous_id` == `raw_amplitude.events.device_id` for cross-source stitching.
