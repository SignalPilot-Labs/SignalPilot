# raw_meta_ads.campaigns

**Source system:** Meta Ads
**Grain:** one row per Meta (Facebook/Instagram) ad campaign
**Approx rows (demo scale):** ~1,200 (customers / 50)
**Loaded by:** warehouse/generators/gen_raw_meta_ads.py

## Business definition
Meta Marketing API ad campaigns across NALA's three regional ad accounts (GBP / USD / EUR). Each row describes a campaign's objective, status, daily budget, and buying type. Parent of ad sets and daily insights; used for paid-acquisition spend/budget reporting on Facebook, Instagram, and Audience Network. Aggregate data — no customer PII.

## Known data-quality quirks
- `daily_budget` is a **DECIMAL string in MINOR units (cents)** — e.g. "200000" = 2,000.00 currency units. This deliberately differs from Google Ads (micros) and from `ad_insights_daily.spend` (major-unit numeric). Cast and divide by 100.
- `status` and `effective_status` can disagree (~15% of rows); `effective_status` may carry `WITH_ISSUES` which is not a valid `status` value. Use `effective_status` for actual delivery state.
- `account_id` is a Meta ad-account id of form `act_<digits>`, NOT a NALA customer.
- `created_time` / `updated_time` are ISO-8601 **text with an explicit tz offset** (`+0000`), not timestamps; cast before date math.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric-string campaign id, primary key |
| account_id | text | no | Meta ad-account id 'act_<digits>' (not a NALA customer) |
| name | text | no | campaign name, e.g. "GBP \| UK Awareness" |
| objective | text | no | OUTCOME_TRAFFIC / OUTCOME_LEADS / OUTCOME_APP_PROMOTION / OUTCOME_AWARENESS |
| status | text | no | ACTIVE / PAUSED / ARCHIVED / DELETED |
| effective_status | text | no | derived delivery status; may differ from status, may be WITH_ISSUES |
| daily_budget | text | no | DECIMAL string in MINOR units / cents (÷100 for currency) |
| buying_type | text | no | AUCTION / RESERVED |
| created_time | text | no | ISO-8601 string with tz offset '+0000' |
| updated_time | text | no | ISO-8601 string with tz offset '+0000' |
| metadata | jsonb | no | vendor blob, e.g. {"special_ad_categories": []} |

## Joins / lineage
- `id` = `raw_meta_ads.ad_sets.campaign_id` = `raw_meta_ads.ad_insights_daily.campaign_id`.
- `account_id` = regional Meta account (GBP act_5510001 / USD act_5510002 / EUR act_5510003).
- No NALA customer linkage (aggregate ad data).
