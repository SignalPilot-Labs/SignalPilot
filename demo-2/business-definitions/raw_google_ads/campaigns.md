# raw_google_ads.campaigns

**Source system:** Google Ads
**Grain:** one row per Google Ads campaign
**Approx rows (demo scale):** ~1,500 (customers / 40)
**Loaded by:** warehouse/generators/gen_raw_google_ads.py

## Business definition
Google Ads acquisition campaigns across NALA's three regional ad accounts (GBP / USD / EUR). Each row describes a campaign's channel type, bidding strategy, daily budget, and run window. Used as the parent for ad groups and daily performance, and for paid-acquisition spend/budget reporting by region and channel. This data is aggregate — there is no customer PII.

## Known data-quality quirks
- `campaign_budget_micros` is in **micros**: divide by 1,000,000 to get currency units (e.g. 50,000,000 = 50.00).
- `customer_id` is the Google Ads **account** id (one of 3 regional accounts), NOT a NALA customer code — do not join it to the customer master.
- `end_date` is null for ongoing campaigns (~60%).
- Account currency must be derived from the account id / labels; it is not stored on this table directly (it lives on `ad_performance_daily.currency_code`).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| campaign_id | bigint | no | Google Ads resource id, primary key |
| customer_id | bigint | no | Google Ads ACCOUNT id (not a NALA customer) |
| name | text | no | campaign name, e.g. "GBP \| UK Brand \| 2023" |
| status | text | no | ENABLED / PAUSED / REMOVED |
| advertising_channel_type | text | no | SEARCH / DISPLAY / VIDEO / PERFORMANCE_MAX |
| bidding_strategy_type | text | no | TARGET_CPA / MAXIMIZE_CONVERSIONS / TARGET_ROAS / MAXIMIZE_CLICKS |
| campaign_budget_micros | bigint | no | daily budget in MICROS (÷1e6 for currency units) |
| start_date | date | no | campaign start date |
| end_date | date | no | campaign end date; null when ongoing |
| labels | jsonb | no | array of label strings (currency, "acquisition") |
| created_at | timestamptz | no | creation time (no-tz ISO formatter) |

## Joins / lineage
- `campaign_id` = `raw_google_ads.ad_groups.campaign_id` = `raw_google_ads.ad_performance_daily.campaign_id`.
- `customer_id` = Google Ads account id (GBP 7100000001 / USD 7100000002 / EUR 7100000003) — account-level, not customer-level.
- No NALA customer linkage (aggregate ad data).
