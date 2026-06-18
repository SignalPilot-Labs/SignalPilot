# raw_google_ads.campaigns

**Source system:** Google Ads API v17 export
**Grain:** one row per Google Ads campaign
**Approx rows (demo scale):** ~1,500
**Loaded by:** warehouse/generators/gen_raw_google_ads.py

## Business definition
Paid-acquisition campaigns NALA runs on Google Ads to acquire new senders across
its send-from regions (UK/US/EU). Aggregate spend data only — no end-customer PII.

## Known data-quality quirks
- `customer_id` is the Google Ads **account** id, NOT a NALA customer.
- `campaign_budget_micros` is in **micros** (1,000,000 micros = 1 currency unit).
- `end_date` is NULL for ongoing campaigns.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| campaign_id | bigint | no | resource id (PK) |
| customer_id | bigint | no | Google Ads account id (not a NALA customer) |
| name | text | no | campaign name |
| status | text | no | ENABLED / PAUSED / REMOVED |
| advertising_channel_type | text | no | SEARCH / DISPLAY / VIDEO / PERFORMANCE_MAX |
| bidding_strategy_type | text | no | TARGET_CPA / MAXIMIZE_CONVERSIONS / ... |
| campaign_budget_micros | bigint | no | daily budget in micros |
| start_date | date | no | campaign start |
| end_date | date | no | nullable (ongoing) |
| labels | jsonb | no | label array |
| created_at | timestamptz | no | created (ISO no-tz origin) |

## Joins / lineage
- `raw_google_ads.ad_groups.campaign_id` → `campaigns.campaign_id`.
- `raw_google_ads.ad_performance_daily.campaign_id` → `campaigns.campaign_id`.
