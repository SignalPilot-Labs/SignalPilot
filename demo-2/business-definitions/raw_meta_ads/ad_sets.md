# raw_meta_ads.ad_sets

**Source system:** Meta Ads
**Grain:** one row per ad set within a campaign
**Approx rows (demo scale):** ~3,000 (~1,200 campaigns × 1-4 ad sets)
**Loaded by:** warehouse/generators/gen_raw_meta_ads.py

## Business definition
Ad sets nested under Meta campaigns — the budget + targeting unit that defines optimization goal, billing event, audience, and bid. Each row carries targeting spec and budget. Used as the join layer between campaigns and daily insights, and for targeting/optimization analysis. Aggregate data — no customer PII.

## Known data-quality quirks
- `daily_budget` and `bid_amount` are **DECIMAL strings in MINOR units (cents)**; cast and divide by 100. Mirrors the campaign quirk and differs from insights `spend` (major-unit numeric).
- `bid_amount` is sparse — null ~50% of the time (ad sets using automatic bidding).
- `created_time` is ISO-8601 text with a tz offset (`+0000`), not a timestamp.
- `status` has no DELETED/ARCHIVED-only nuance here (ACTIVE / PAUSED / ARCHIVED).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric-string ad set id, primary key |
| campaign_id | text | no | -> raw_meta_ads.campaigns.id |
| name | text | no | ad set name, e.g. "AdSet 7 - LAL1%" |
| status | text | no | ACTIVE / PAUSED / ARCHIVED |
| optimization_goal | text | no | LINK_CLICKS / OFFSITE_CONVERSIONS / APP_INSTALLS / LANDING_PAGE_VIEWS |
| billing_event | text | no | IMPRESSIONS / LINK_CLICKS |
| bid_amount | text | no | DECIMAL string minor units; null ~50% (auto bidding) |
| daily_budget | text | no | DECIMAL string in MINOR units / cents (÷100 for currency) |
| targeting | jsonb | no | targeting spec blob (geo_locations, age_min/max) |
| created_time | text | no | ISO-8601 string with tz offset '+0000' |

## Joins / lineage
- `campaign_id` -> `raw_meta_ads.campaigns.id`.
- `id` = `raw_meta_ads.ad_insights_daily.adset_id` (note: insights uses `adset_id`, not `ad_set_id`).
- No NALA customer linkage (aggregate ad data).
