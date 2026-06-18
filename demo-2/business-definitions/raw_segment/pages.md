# raw_segment.pages

**Source system:** Segment
**Grain:** one row per web `page` call (a page view on the marketing site or web app)
**Approx rows (demo scale):** ~1,250,000
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Segment `page` calls from NALA's marketing site and web app (Home, Pricing, Send Money, etc.). Used for web funnel analysis, landing-page performance, and acquisition attribution on the web surface, before users identify or move to the mobile app.

## Known data-quality quirks
- `user_id` is NULL for ~70% of rows (web traffic is mostly anonymous).
- `category` is ~60% null (only sometimes tagged `marketing`).
- `context_ip` ~5% null.
- `properties` jsonb holds url/path/referrer/title; referrer can be an empty string.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id (PK) |
| anonymous_id | text | yes | Browser anonymous id (always present) |
| user_id | text | yes | `CUS_...` code; usually NULL on web (~70%) |
| name | text | no | Page name (Home, Pricing, Send Money, ...) |
| category | text | no | Page category (~60% null) |
| properties | jsonb | no | {url, path, referrer, title} |
| context_ip | inet | yes | Client IP (~5% null) |
| context_page_url | text | no | Full page URL |
| context_page_referrer | text | no | Referrer URL (may be empty) |
| context_user_agent | text | no | Browser user agent string |
| timestamp | timestamptz | no | Page view time |
| received_at | timestamptz | no | When Segment received (load watermark) |

## Joins / lineage
- `anonymous_id` → `raw_segment.identifies.anonymous_id` to resolve `user_id` for anonymous web sessions.
- `user_id` = customer code → `common.customer_master` (when present).
