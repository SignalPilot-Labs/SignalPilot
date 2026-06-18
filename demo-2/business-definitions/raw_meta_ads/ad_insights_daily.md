# raw_meta_ads.ad_insights_daily

**Source system:** Meta Ads
**Grain:** one row per ad set per day (per publisher platform)
**Approx rows (demo scale):** ~750K (~3,000 ad sets × ~365-day window, ~70% of days deliver)
**Loaded by:** warehouse/generators/gen_raw_meta_ads.py

## Business definition
The Meta fact table: daily aggregate delivery metrics (impressions, clicks, spend, reach, actions) per ad set. Source of truth for Meta paid-acquisition spend, reach, and conversion analysis by campaign, ad set, platform, and region. Conversions (installs, purchases) live inside the `actions` JSON. Aggregate data — no customer PII.

## Known data-quality quirks
- `spend` is `numeric(18,2)` in **MAJOR units (account currency)** — this deliberately differs from the campaign/ad-set `daily_budget` columns, which are minor-unit DECIMAL strings. Do not divide `spend` by 100.
- Conversions are NOT columns: they live in the `actions` JSON array as `{action_type, value}` objects where `value` is a **string**. Expect `mobile_app_install`, `offsite_conversion.fb_pixel_purchase`, `link_click`. `actions` is null when there were none.
- `adset_id` is named with Meta's `adset` spelling (not `ad_set`); join carefully.
- `date_stop` always equals `date_start` for this daily breakdown.
- Not every ad set delivers every day (~30% of ad-set-days skipped). Window is bounded (~365 days at demo scale, 60 at test scale).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate row id, primary key |
| date_start | date | no | metrics date (Meta 'date_start') |
| date_stop | date | no | equals date_start for daily breakdown |
| account_id | text | no | Meta ad-account id 'act_<digits>' |
| campaign_id | text | no | -> raw_meta_ads.campaigns.id |
| adset_id | text | no | -> raw_meta_ads.ad_sets.id (note 'adset' spelling) |
| publisher_platform | text | no | facebook / instagram / audience_network |
| impressions | bigint | no | impression count |
| clicks | bigint | no | click count |
| spend | numeric(18,2) | no | spend in MAJOR units (account currency) — not minor |
| reach | bigint | no | unique reach count |
| actions | jsonb | no | array of {action_type, value(string)}; conversions live here; null when none |
| account_currency | text | no | GBP / USD / EUR |
| loaded_at | timestamptz | no | ETL load time (string-formatted) |

## Joins / lineage
- `campaign_id` -> `raw_meta_ads.campaigns.id`; `adset_id` -> `raw_meta_ads.ad_sets.id`.
- Conversions require JSON expansion of `actions` (string values).
- No NALA customer linkage (aggregate ad data).
