# raw_app_store.google_play_reviews

**Source system:** Google Play
**Grain:** one row per Play Store review
**Approx rows (demo scale):** ~12,000
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Individual Google Play Store reviews (1–5 star rating, free-text, optional developer reply). Android counterpart to `apple_reviews` for voice-of-customer and app-quality analysis; ~80% positive, mirroring NALA's high store rating. Negative reviews flag stuck transfers, KYC friction, and crashes.

## Known data-quality quirks
- Free-text `review_text` and `author_name` may contain PII.
- `author_name` is ~10% null; `review_title` is ~30% null (Play reviews often have no title).
- `developer_reply_text` / `developer_reply_at` only populated when NALA replied (~50% of negative reviews); `last_modified_at` ~70% null.
- Uses Google numeric `app_version_code` alongside `app_version_name`.
- No customer join key (reviews are anonymous).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| review_id | text | no | Play review id (PK) |
| package_name | text | no | `com.nala.app` |
| author_name | text | yes | Reviewer display name (~10% null) |
| star_rating | integer | no | Star rating 1..5 |
| review_title | text | no | Review title (~30% null) |
| review_text | text | yes | Free-text (may contain PII) |
| reviewer_language | text | no | en / fr / sw / en-GB |
| device | text | no | Device model |
| android_os_version | text | no | Android OS version |
| app_version_code | integer | no | Numeric Android version code |
| app_version_name | text | no | Human version name |
| submitted_at | timestamptz | no | Review submit date/time |
| last_modified_at | timestamptz | no | Last modified time (~70% null) |
| developer_reply_text | text | no | NALA reply text (often null) |
| developer_reply_at | timestamptz | no | Reply time (null if no reply) |

## Joins / lineage
- No customer-level join (anonymous). Relates temporally/geographically on (`submitted_at`, country via funnel) and by version to release analysis.
