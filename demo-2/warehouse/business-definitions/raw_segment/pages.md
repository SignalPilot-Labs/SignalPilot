# raw_segment.pages

**Source system:** Segment (Connections — `page` calls, web)
**Grain:** one row per web `page` view
**Approx rows (demo scale):** ~1,250,000 (`N["events"]` / 4)
**Loaded by:** warehouse/generators/gen_raw_segment.py

## Business definition
Web pageviews from the NALA marketing site and web app (Home, Pricing, Send Money, signup, Rafiki, etc.). Feeds web-funnel and acquisition-landing analysis.

## Known data-quality quirks
- `user_id` is NULL for ~70% of rows (web traffic is mostly anonymous).
- `category` is ~60% null.
- `context_page_referrer` is often an empty string rather than null.
- `context_ip` ~5% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Segment message id. PK. |
| anonymous_id | text | yes | Browser anon id. |
| user_id | text | yes | Customer code CUS_...; usually NULL on web. |
| name | text | no | Page name ('Home', 'Pricing', 'Send Money'). |
| category | text | no | Page category; sparse. |
| properties | jsonb | no | {url, path, referrer, title}. |
| context_ip | inet | yes | Client IP. |
| context_page_url | text | no | Full page URL. |
| context_page_referrer | text | no | Referrer URL (may be empty string). |
| context_user_agent | text | no | Browser UA. |
| timestamp | timestamptz | no | Event time. |
| received_at | timestamptz | no | Load watermark. |

## Joins / lineage
- `anonymous_id` → `raw_segment.identifies.anonymous_id` (stitch web sessions to a user).
- `user_id` → `raw_core_transfers.customers.customer_code` (when present).
- No staging model (low-priority table).
