# raw_appsflyer.media_sources

**Source system:** AppsFlyer
**Grain:** one row per acquisition channel / ad network
**Approx rows (demo scale):** 7
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
Lookup of the acquisition channels and ad networks NALA buys on (Facebook Ads, Google Ads, TikTok, Apple Search Ads, Snapchat, Organic, Referral). Provides clean channel names and a channel-type classification used to roll up paid vs organic acquisition in install and attribution reporting.

## Known data-quality quirks
- Small static lookup (7 rows).
- `media_source` is the raw vendor string used as the join key into install/event/attribution tables, and those source columns are dirty/free-text — joins can miss.
- `pretty_name` is the display label; `channel_type` buckets into paid_social / paid_search / organic / referral.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| media_source_id | integer | no | Surrogate id (PK) |
| media_source | text | no | Raw source string (e.g. `googleadwords_int`, `Organic`) |
| pretty_name | text | no | Display name (Facebook, Google Ads, TikTok, Organic) |
| channel_type | text | no | paid_social / paid_search / organic / referral |
| is_active | boolean | no | Whether the channel is currently active |

## Joins / lineage
- `media_source` ← `raw_appsflyer.installs.media_source`, `in_app_events.media_source`, `attributions.media_source` (dirty free-text join; expect non-matches).
