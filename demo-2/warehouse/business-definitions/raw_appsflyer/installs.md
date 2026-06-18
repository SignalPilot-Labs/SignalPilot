# raw_appsflyer.installs

**Source system:** AppsFlyer (Raw Data / Push API — install postbacks)
**Grain:** one row per app install / first-open (one per customer device)
**Approx rows (demo scale):** ~60,000 (`N["customers"]`)
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
Attributed mobile installs: which channel/campaign got credit for each new install, plus device and geo. The backbone of acquisition reporting, CAC, and channel ROI.

## Known data-quality quirks
- **`install_time` and `attributed_touch_time` are naive UTC ISO *strings* (text)**, format `YYYY-MM-DD HH:MM:SS` — parse with `to_timestamp(..., 'YYYY-MM-DD HH24:MI:SS')`. (Contrast `attributions.touch_time`, which is a real timestamptz.)
- `customer_user_id` ~18% null (install happened before login).
- `media_source` is dirty (vendor casing); ~45% organic (campaign fields null on organic).
- `idfa` ~40% null on iOS (ATT denial); `advertising_id` only on Android.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| appsflyer_id | text | yes | AppsFlyer device id. PK. |
| customer_user_id | text | yes | Customer code CUS_...; ~18% null pre-login. |
| install_time | text | no | Naive UTC ISO string. |
| attributed_touch_time | text | no | Naive ISO string; null on organic. |
| attributed_touch_type | text | no | click / impression. |
| media_source | text | no | Raw source (join to media_sources). |
| campaign / campaign_id / af_adset / af_ad / af_channel | text | no | Ad hierarchy; null on organic. |
| platform | text | no | ios / android. |
| app_id | text | no | iOS app id / android package. |
| app_version | text | no | App build. |
| device_model / os_version | text | no | Device info. |
| country_code | text | no | ISO-2. |
| language | text | no | Locale. |
| idfa | text | yes | iOS advertising id; ~40% null. |
| idfv | text | yes | iOS vendor id. |
| advertising_id | text | yes | Android GAID. |
| ip | inet | yes | Client IP. |
| is_organic / is_retargeting / is_primary_attribution | boolean | no | Attribution flags. |

## Joins / lineage
- `customer_user_id` → `raw_core_transfers.customers.customer_code`.
- `media_source` → `raw_appsflyer.media_sources.media_source`.
- `appsflyer_id` → `raw_appsflyer.in_app_events.appsflyer_id` and `attributions.appsflyer_id`.
- Staging: `stg_appsflyer__installs` (parses the ISO strings to timestamptz).
