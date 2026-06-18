# raw_appsflyer.attributions

**Source system:** AppsFlyer (attribution decision records)
**Grain:** one row per attribution decision (install / reattribution / reengagement)
**Approx rows (demo scale):** ~120,000 (`N["customers"]` × 2)
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
The attribution-decision log: which touch got credit for an install or re-engagement, the touch type, and any multi-touch contributor. Used to audit attribution and analyze reattribution/reengagement behavior.

## Known data-quality quirks
- **`touch_time` and `attributed_at` are real `timestamptz`** here — different from `installs.attributed_touch_time` (which is a text ISO string). Watch the type mismatch when joining.
- `customer_user_id` ~20% null.
- `contributor_1_media_source` ~70% null (single-touch is common).
- ~40% organic (campaign fields null).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| attribution_id | text | no | PK. |
| appsflyer_id | text | yes | Device id (→ installs.appsflyer_id). |
| customer_user_id | text | yes | Customer code CUS_...; ~20% null. |
| media_source / campaign / campaign_id | text | no | Attributed channel. |
| attribution_type | text | no | install / reattribution / reengagement. |
| touch_type | text | no | click / impression. |
| touch_time | timestamptz | no | When the attributed touch occurred. |
| attributed_at | timestamptz | no | When attribution was decided. |
| contributor_1_media_source | text | no | Multi-touch contributor; ~70% null. |
| is_organic | boolean | no | Organic attribution flag. |

## Joins / lineage
- `appsflyer_id` → `raw_appsflyer.installs.appsflyer_id`.
- `customer_user_id` → `raw_core_transfers.customers.customer_code`.
- `media_source` → `raw_appsflyer.media_sources.media_source`.
- No staging model.
