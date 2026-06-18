# raw_google_ads.ad_performance_daily

**Source system:** Google Ads
**Grain:** one row per ad group per day (dominant device)
**Approx rows (demo scale):** ~1.4M (~5,250 ad groups × ~365-day window, ~75% of days spend)
**Loaded by:** warehouse/generators/gen_raw_google_ads.py

## Business definition
The Google Ads fact table: daily aggregate performance metrics (impressions, clicks, cost, conversions, conversion value) per ad group. This is the source of truth for paid-acquisition spend and ROAS analysis by campaign, ad group, device, and region. Aggregate data — no customer PII.

## Known data-quality quirks
- `cost_micros` is in **micros**: divide by 1,000,000 to get currency units. The currency is given by `currency_code` (the account currency), which differs across the three regional accounts.
- `conversions` is fractional `numeric(12,2)` (attribution can assign partial conversions) — do not assume integers.
- `ctr` is a legacy precomputed value and is null/stale ~10% of the time; recompute as `clicks / impressions` rather than trusting it.
- Not every ad group has a row every day (~25% of group-days are skipped), and rows only exist on/after the campaign `start_date`. The window is bounded (~365 days at demo scale, 60 at test scale).
- One dominant `device` per group-day; this is not a full device-level breakdown.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate row id, primary key |
| date | date | no | metrics date ('segments.date') |
| campaign_id | bigint | no | -> raw_google_ads.campaigns.campaign_id |
| ad_group_id | bigint | no | -> raw_google_ads.ad_groups.ad_group_id |
| device | text | no | MOBILE / DESKTOP / TABLET (dominant device for the row) |
| impressions | bigint | no | impression count |
| clicks | bigint | no | click count |
| cost_micros | bigint | no | spend in MICROS (÷1e6 for currency units) |
| conversions | numeric(12,2) | no | fractional attributed conversions |
| conversions_value | numeric(18,2) | no | attributed value in account currency |
| currency_code | text | no | account currency: GBP / USD / EUR |
| ctr | numeric(8,5) | no | legacy precomputed CTR; null/stale ~10% — recompute |
| loaded_at | timestamptz | no | ETL load time (no-tz ISO formatter) |

## Joins / lineage
- `campaign_id` -> `raw_google_ads.campaigns.campaign_id`; `ad_group_id` -> `raw_google_ads.ad_groups.ad_group_id`.
- No NALA customer linkage (aggregate ad data).
