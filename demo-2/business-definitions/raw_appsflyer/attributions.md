# raw_appsflyer.attributions

**Source system:** AppsFlyer
**Grain:** one row per attribution decision record (install / reattribution / reengagement)
**Approx rows (demo scale):** ~120,000
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
AppsFlyer attribution decision records that capture which touch got credit for an install or re-engagement, including multi-touch contributor data. Used to audit attribution logic, analyze reattribution/reengagement, and reconcile credited media sources against the install table.

## Known data-quality quirks
- `touch_time` is a real `timestamptz` here — different from `installs.attributed_touch_time` (a naive ISO string). Cross-source time joins must reconcile the two formats.
- `media_source`, `campaign`, `campaign_id`, and `touch_type` are NULL for organic records (~40%).
- `contributor_1_media_source` is sparse (~70% null) — only populated for multi-touch attributions.
- `customer_user_id` is ~20% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| attribution_id | text | no | Attribution record id (PK) |
| appsflyer_id | text | yes | → installs.appsflyer_id (device key) |
| customer_user_id | text | yes | `CUS_...` code; ~20% null |
| media_source | text | no | Credited media source; null for organic |
| campaign | text | no | Campaign name; null for organic |
| campaign_id | text | no | Campaign id; null for organic |
| attribution_type | text | no | install / reattribution / reengagement |
| touch_type | text | no | click / impression; null for organic |
| touch_time | timestamptz | no | Touch time (real timestamptz — differs from installs!) |
| attributed_at | timestamptz | no | When attribution was decided |
| contributor_1_media_source | text | no | Multi-touch contributor source (~70% null) |
| is_organic | boolean | no | Whether the attribution was organic |

## Joins / lineage
- `appsflyer_id` → `raw_appsflyer.installs.appsflyer_id`.
- `customer_user_id` = customer code → `common.customer_master`.
- `media_source` → `raw_appsflyer.media_sources.media_source` (dirty join).
