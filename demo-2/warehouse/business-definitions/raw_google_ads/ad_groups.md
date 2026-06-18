# raw_google_ads.ad_groups

**Source system:** Google Ads API v17 export
**Grain:** one row per ad group
**Approx rows (demo scale):** ~5,000
**Loaded by:** warehouse/generators/gen_raw_google_ads.py

## Business definition
Ad groups nested under Google Ads campaigns; the level at which bids are set and
at which daily performance is reported.

## Known data-quality quirks
- `cpc_bid_micros` is in micros.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| ad_group_id | bigint | no | resource id (PK) |
| campaign_id | bigint | no | → campaigns.campaign_id |
| name | text | no | ad group name |
| status | text | no | ENABLED / PAUSED / REMOVED |
| type | text | no | SEARCH_STANDARD / DISPLAY_STANDARD |
| cpc_bid_micros | bigint | no | CPC bid in micros |
| created_at | timestamptz | no | created |

## Joins / lineage
- `campaign_id` → `raw_google_ads.campaigns.campaign_id`.
- `raw_google_ads.ad_performance_daily.ad_group_id` → `ad_groups.ad_group_id`.
