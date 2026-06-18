# raw_app_store.google_play_reviews

**Source system:** Google Play Console (Reviews)
**Grain:** one row per Play Store review
**Approx rows (demo scale):** ~12,000 (`N["customers"]` / 5)
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Individual Android Play Store reviews — star rating, free-text, author display name, device/OS, and any NALA developer reply. The Android counterpart to `apple_reviews`; feeds rating tracking and voice-of-customer / sentiment analysis.

## Known data-quality quirks
- Ratings skew positive (~80% 4–5 stars).
- `author_name` ~10% null; `review_title` ~30% null (Play reviews often have no title).
- `review_text` is free-text and may contain PII.
- `developer_reply_text`/`developer_reply_at` null unless NALA replied; `last_modified_at` ~70% null.
- Uses numeric `app_version_code` plus a separate `app_version_name`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| review_id | text | no | Play review id. PK. |
| package_name | text | no | 'com.nala.app'. |
| author_name | text | yes | Reviewer display name; ~10% null. |
| star_rating | integer | no | 1..5. |
| review_title | text | maybe | Review title; ~30% null. |
| review_text | text | maybe | Free-text (may contain PII). |
| reviewer_language | text | no | en / fr / sw / en-GB. |
| device | text | no | Device model. |
| android_os_version | text | no | Android version. |
| app_version_code | integer | no | Numeric Play version code. |
| app_version_name | text | no | Semver app version. |
| submitted_at | timestamptz | no | Review submit time. |
| last_modified_at | timestamptz | no | Last edit; ~70% null. |
| developer_reply_text | text | no | NALA reply text. |
| developer_reply_at | timestamptz | no | Reply time. |

## Joins / lineage
- No customer key (pseudonymous). No FK.
- Staging: `stg_app_store__google_play_reviews` (aligned shape with the Apple-reviews staging model for downstream union).
