# raw_braze.campaigns

**Source system:** Braze
**Grain:** one row per single-step Braze messaging campaign
**Approx rows (demo scale):** ~3,000 (customers / 20)
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Single-step messaging campaigns run on Braze for NALA's lifecycle/CRM marketing (welcome series, first-transfer bonus, FX rate alerts, reactivation, corridor promos). Each row describes one campaign's channel, messaging type, status, and send window. Used to attribute `raw_braze.messages_sent` events to a named campaign and to report on CRM program activity.

## Known data-quality quirks
- `status` includes a legacy value `STOPPED` alongside the modern `active` / `draft` / `archived` set; treat `STOPPED` as inactive.
- `first_sent` and `last_sent` are ISO-8601 text with a `Z` suffix (not timestamps); cast before date math.
- `updated_at` is generated via a no-tz ISO formatter while `created_at` carries tz — timezone handling differs across the two columns.
- `first_sent` is null ~15% of the time (campaign never sent); `last_sent` is null whenever `first_sent` is null.
- `is_archived` is only true when `status = 'archived'`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| campaign_id | text | no | 24-hex Braze api_id, primary key |
| name | text | no | campaign name, e.g. "First Transfer Bonus - email" |
| channel | text | no | email / push / in_app_message / sms / webhook |
| messaging_type | text | no | promotional / transactional |
| tags | jsonb | no | array of tag strings (growth, lifecycle, promo, ...) |
| status | text | no | active / draft / archived / STOPPED (legacy) |
| is_archived | boolean | no | true only when status = archived; defaults false |
| first_sent | text | no | ISO-Z string, first send time; nullable |
| last_sent | text | no | ISO-Z string, last send time; null when first_sent null |
| created_at | timestamptz | no | creation time (tz-aware) |
| updated_at | timestamptz | no | last update; emitted via no-tz ISO formatter |
| metadata | jsonb | no | vendor payload blob, e.g. {"team": "growth"} |

## Joins / lineage
- `campaign_id` = `raw_braze.messages_sent.campaign_id` (campaign-sourced sends).
- No customer linkage at this grain; customer attribution lives in `messages_sent`.
