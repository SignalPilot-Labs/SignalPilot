# raw_appsflyer.media_sources

**Source system:** AppsFlyer (channel configuration)
**Grain:** one row per acquisition channel / ad network
**Approx rows (demo scale):** 7
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
Lookup of the paid and organic acquisition channels NALA buys on (Facebook Ads, Google Ads, TikTok, Apple Search Ads, Snapchat, Organic, referral). Maps the raw `media_source` string seen on installs/events to a friendly name and channel type for CAC and ROI reporting.

## Known data-quality quirks
- The raw `media_source` string on `installs`/`in_app_events` is dirty (vendor casing like `googleadwords_int`, `tiktokglobal_int`) — join on `media_source`, not pretty_name.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| media_source_id | integer | no | PK. |
| media_source | text | no | Raw source string ('googleadwords_int', 'Organic'). |
| pretty_name | text | no | Friendly name ('Google Ads', 'Organic'). |
| channel_type | text | no | paid_social / paid_search / organic / referral. |
| is_active | boolean | no | Channel currently in use. |

## Joins / lineage
- `media_source` ← `raw_appsflyer.installs.media_source` and `in_app_events.media_source` (dirty key).
- No staging model.
