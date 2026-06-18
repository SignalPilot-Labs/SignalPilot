# raw_meta_ads.ad_insights_daily

**Source system:** Meta Marketing API v20 (Insights edge)
**Grain:** one row per ad_set per day per publisher_platform (aggregate)
**Approx rows (demo scale):** ~hundreds of thousands
**Loaded by:** warehouse/generators/gen_raw_meta_ads.py

## Business definition
Daily aggregate paid-social performance: impressions, clicks, spend, reach and
conversion actions per ad set. Primary table for Meta marketing spend / CAC.
Aggregate only — contains **no customer PII**.

## Known data-quality quirks
- Column is `adset_id` (Meta spelling), not `ad_set_id`.
- `spend` is in account-currency **major units** (numeric) — differs from Google's micros.
- Conversions are NOT a column: they live inside the `actions` JSON array as `{action_type, value}` (e.g. `mobile_app_install`, `offsite_conversion.fb_pixel_purchase`); `actions` can be NULL.
- `date_stop` equals `date_start` for the daily breakdown.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate PK |
| date_start | date | no | report date |
| date_stop | date | no | == date_start |
| account_id | text | no | ad account |
| campaign_id | text | no | → campaigns.id |
| adset_id | text | no | → ad_sets.id |
| publisher_platform | text | no | facebook / instagram / audience_network |
| impressions | bigint | no | impressions |
| clicks | bigint | no | clicks |
| spend | numeric(18,2) | no | spend in account ccy (major units) |
| reach | bigint | no | unique reach |
| actions | jsonb | no | array of {action_type, value}; conversions here |
| account_currency | text | no | account currency |
| loaded_at | timestamptz | no | ETL load time |

## Joins / lineage
- `campaign_id` → `raw_meta_ads.campaigns.id`; `adset_id` → `raw_meta_ads.ad_sets.id`.
