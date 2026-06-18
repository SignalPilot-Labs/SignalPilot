# raw_google_ads.ad_performance_daily

**Source system:** Google Ads API v17 (metrics + segments.date)
**Grain:** one row per ad_group per day per device (aggregate)
**Approx rows (demo scale):** ~hundreds of thousands
**Loaded by:** warehouse/generators/gen_raw_google_ads.py

## Business definition
Daily aggregate paid-search/display performance: impressions, clicks, spend and
attributed conversions per ad group. The primary table for marketing spend and
CAC analysis. Aggregate only — contains **no customer PII**.

## Known data-quality quirks
- `cost_micros` is in **micros** (÷1,000,000 for currency units); `currency_code` is the account currency.
- `conversions` is fractional (fractional attribution).
- `ctr` is a legacy precomputed ratio and is ~10% NULL/stale — recompute from clicks/impressions.
- Rows are sparse: not every ad group has a row every day.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate PK |
| date | date | no | report date |
| campaign_id | bigint | no | → campaigns |
| ad_group_id | bigint | no | → ad_groups |
| device | text | no | MOBILE / DESKTOP / TABLET |
| impressions | bigint | no | impressions |
| clicks | bigint | no | clicks |
| cost_micros | bigint | no | spend in micros |
| conversions | numeric(12,2) | no | fractional conversions |
| conversions_value | numeric(18,2) | no | attributed value (account ccy) |
| currency_code | text | no | account currency |
| ctr | numeric(8,5) | no | legacy precomputed CTR, stale/null |
| loaded_at | timestamptz | no | ETL load time |

## Joins / lineage
- `campaign_id` → `raw_google_ads.campaigns`; `ad_group_id` → `raw_google_ads.ad_groups`.
