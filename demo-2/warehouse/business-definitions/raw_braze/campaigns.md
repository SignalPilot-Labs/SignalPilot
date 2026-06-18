# raw_braze.campaigns

**Source system:** Braze (customer-engagement / messaging platform), REST export
**Grain:** one row per single-step messaging campaign
**Approx rows (demo scale):** ~3,000
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Marketing/CRM campaigns NALA runs in Braze to drive sends, reactivation, KYC
completion and referrals across email, push, SMS and in-app channels. Used by
the growth/lifecycle teams to attribute engagement and message volume.

## Known data-quality quirks
- `first_sent` / `last_sent` are ISO-Z **text** strings, not timestamps; null on never-sent drafts.
- `status` carries a legacy free-text value `STOPPED` alongside active/draft/archived.
- `updated_at` is an ISO string with **no timezone** (legacy naming `updated`-style).
- `tags` / `metadata` are JSON blobs.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| campaign_id | text | no | 24-hex Braze api_id (PK) |
| name | text | no | campaign name (theme + channel) |
| channel | text | no | email / push / in_app_message / sms / webhook |
| messaging_type | text | no | promotional / transactional |
| tags | jsonb | no | array of tag strings |
| status | text | no | active / draft / archived / STOPPED (legacy) |
| is_archived | boolean | no | archived flag |
| first_sent | text | no | ISO-Z string, nullable |
| last_sent | text | no | ISO-Z string, nullable |
| created_at | timestamptz | no | tz-aware |
| updated_at | timestamptz | no | ISO string no-tz origin |
| metadata | jsonb | no | vendor payload blob |

## Joins / lineage
- `raw_braze.messages_sent.campaign_id` → `campaigns.campaign_id`.
