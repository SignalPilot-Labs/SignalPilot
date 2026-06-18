# raw_app_store.apple_reviews

**Source system:** Apple App Store Connect (Customer Reviews API)
**Grain:** one row per App Store review
**Approx rows (demo scale):** ~10,000 (`N["customers"]` / 6)
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Individual iOS App Store reviews — star rating, free-text title/body, reviewer nickname, and any NALA developer response. Feeds app-rating tracking (NALA averages ~4.8) and voice-of-customer / sentiment analysis.

## Known data-quality quirks
- Ratings skew positive (~82% are 4–5 stars), matching NALA's ~4.8 average.
- `reviewer_nickname` ~5% null; `body`/`title` are free-text and may contain PII.
- `developer_response`/`developer_response_date` are null unless NALA replied (mostly on negative reviews).
- `review_date` is a tz timestamp (ISO-Z style).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| review_id | text | no | App Store Connect review id. PK. |
| territory | text | no | Storefront ISO-2. |
| rating | integer | no | 1..5. |
| title | text | maybe | Review title (free-text). |
| body | text | maybe | Review body (free-text; may contain PII). |
| reviewer_nickname | text | yes | Display nickname; ~5% null. |
| app_version | text | no | App build. |
| is_edited | boolean | no | Review was edited. |
| review_date | timestamptz | no | When submitted. |
| developer_response | text | no | NALA reply text; often null. |
| developer_response_date | timestamptz | no | Reply time. |
| raw_payload | jsonb | no | Original review JSON. |

## Joins / lineage
- No customer key (reviews are pseudonymous). No FK.
- Staging: `stg_app_store__apple_reviews` (aligned shape with the Play-reviews staging model for downstream union).
