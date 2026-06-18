# raw_meta_ads.campaigns

**Source system:** Meta Marketing API v20 export
**Grain:** one row per Meta (Facebook/Instagram) campaign
**Approx rows (demo scale):** ~1,200
**Loaded by:** warehouse/generators/gen_raw_meta_ads.py

## Business definition
Paid-social acquisition campaigns NALA runs on Meta to acquire diaspora senders.
Aggregate spend data only — no end-customer PII.

## Known data-quality quirks
- `id` and `campaign_id` references are **numeric strings** (kept as text per the API).
- `daily_budget` is a DECIMAL **string in minor units (cents)** — differs from Google's micros.
- `status` vs `effective_status` can disagree (effective is derived; may be WITH_ISSUES).
- `created_time` / `updated_time` are ISO strings with explicit tz offset `+0000`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric string id (PK) |
| account_id | text | no | 'act_<digits>' ad account (not a NALA customer) |
| name | text | no | campaign name |
| objective | text | no | OUTCOME_TRAFFIC / OUTCOME_LEADS / OUTCOME_APP_PROMOTION |
| status | text | no | ACTIVE / PAUSED / ARCHIVED / DELETED |
| effective_status | text | no | derived status, may differ |
| daily_budget | text | no | DECIMAL string, minor units (cents) |
| buying_type | text | no | AUCTION / RESERVED |
| created_time | text | no | ISO with tz offset |
| updated_time | text | no | ISO with tz offset |
| metadata | jsonb | no | vendor payload |

## Joins / lineage
- `raw_meta_ads.ad_sets.campaign_id` → `campaigns.id`.
- `raw_meta_ads.ad_insights_daily.campaign_id` → `campaigns.id`.
