# raw_meta_ads.ad_sets

**Source system:** Meta Marketing API v20 export
**Grain:** one row per ad set
**Approx rows (demo scale):** ~3,000
**Loaded by:** warehouse/generators/gen_raw_meta_ads.py

## Business definition
Ad sets (targeting + budget unit) nested under Meta campaigns; the level at which
daily insights are reported.

## Known data-quality quirks
- `bid_amount` and `daily_budget` are DECIMAL **strings in minor units**; `bid_amount` ~50% NULL.
- `targeting` is a JSON spec blob.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric string id (PK) |
| campaign_id | text | no | → campaigns.id |
| name | text | no | ad set name |
| status | text | no | ACTIVE / PAUSED / ARCHIVED |
| optimization_goal | text | no | LINK_CLICKS / OFFSITE_CONVERSIONS / APP_INSTALLS |
| billing_event | text | no | IMPRESSIONS / LINK_CLICKS |
| bid_amount | text | no | DECIMAL string minor units, sparse |
| daily_budget | text | no | DECIMAL string minor units |
| targeting | jsonb | no | targeting spec blob |
| created_time | text | no | ISO with tz offset |

## Joins / lineage
- `campaign_id` → `raw_meta_ads.campaigns.id`.
- `raw_meta_ads.ad_insights_daily.adset_id` → `ad_sets.id`.
