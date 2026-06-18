# raw_google_ads.ad_groups

**Source system:** Google Ads
**Grain:** one row per ad group within a campaign
**Approx rows (demo scale):** ~5,250 (~1,500 campaigns × 2-5 ad groups)
**Loaded by:** warehouse/generators/gen_raw_google_ads.py

## Business definition
Ad groups nested under Google Ads campaigns — the targeting/bidding unit that owns keywords and ads. Each row carries the ad group's type, status, and CPC bid. Used as the join layer between campaigns and the daily performance fact. Aggregate data with no customer PII.

## Known data-quality quirks
- `cpc_bid_micros` is in **micros**: divide by 1,000,000 to get currency units.
- `type` is derived from the parent campaign's channel type: `SEARCH_STANDARD` when the campaign is SEARCH, otherwise `DISPLAY_STANDARD` (so VIDEO/PERFORMANCE_MAX campaigns still show DISPLAY_STANDARD here).
- `status` has no `REMOVED` value at this grain (only ENABLED / PAUSED), unlike campaigns.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| ad_group_id | bigint | no | resource id, primary key |
| campaign_id | bigint | no | -> raw_google_ads.campaigns.campaign_id |
| name | text | no | ad group name, e.g. "AG 12 - Exact" |
| status | text | no | ENABLED / PAUSED |
| type | text | no | SEARCH_STANDARD / DISPLAY_STANDARD (derived from campaign) |
| cpc_bid_micros | bigint | no | CPC bid in MICROS (÷1e6 for currency units) |
| created_at | timestamptz | no | creation time (no-tz ISO formatter) |

## Joins / lineage
- `campaign_id` -> `raw_google_ads.campaigns.campaign_id`.
- `ad_group_id` = `raw_google_ads.ad_performance_daily.ad_group_id`.
- No NALA customer linkage (aggregate ad data).
