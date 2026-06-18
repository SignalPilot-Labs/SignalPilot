# raw_app_store.apple_reviews

**Source system:** Apple App Store
**Grain:** one row per App Store customer review
**Approx rows (demo scale):** ~10,000
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Individual App Store customer reviews (1–5 star rating, free-text title/body, optional developer response). Used for app-quality and voice-of-customer analysis; NALA's ~4.8 average rating skew shows up here (~82% positive). Negative reviews surface KYC, stuck-transfer, and fee complaints.

## Known data-quality quirks
- Free-text `body` and `reviewer_nickname` may contain PII.
- `reviewer_nickname` is ~5% null.
- `developer_response` / `developer_response_date` are only populated when NALA replied (~60% of negative reviews only); null otherwise.
- `is_edited` true for ~5% of reviews.
- `raw_payload` jsonb is a minimal stub, not a full review API payload.
- No customer join key (store reviews are anonymous).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| review_id | text | no | App Store Connect review id (PK) |
| territory | text | no | Storefront country (ISO-2) |
| rating | integer | no | Star rating 1..5 |
| title | text | no | Review title |
| body | text | yes | Review free-text (may contain PII) |
| reviewer_nickname | text | yes | Display nickname (~5% null) |
| app_version | text | no | App version reviewed |
| is_edited | boolean | no | Whether the review was edited (~5%) |
| review_date | timestamptz | no | Review submission time (ISO-Z tz) |
| developer_response | text | no | NALA reply text (often null) |
| developer_response_date | timestamptz | no | Reply time (null if no reply) |
| raw_payload | jsonb | no | Original review JSON (stub) |

## Joins / lineage
- No customer-level join (anonymous). Relates temporally/geographically on (`review_date`, `territory`) and by `app_version` to release/funnel analysis.
