# raw_appsflyer.installs

**Source system:** AppsFlyer
**Grain:** one row per first-open / install (one per customer)
**Approx rows (demo scale):** ~60,000
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
AppsFlyer mobile-attribution (MMP) install records — one attributed first-open per customer with the media source, campaign, and touch metadata that won credit. This is the foundation of paid-acquisition / CAC reporting and the entry point of the mobile install-to-transfer funnel.

## Known data-quality quirks
- `install_time` and `attributed_touch_time` are naive UTC ISO **strings** (text), not timestamps — vendor format drift; cast before time math. Contrast with `attributions.touch_time`, which is a real `timestamptz`.
- `attributed_touch_time` and all campaign fields (campaign, campaign_id, af_adset, af_ad, af_channel, attributed_touch_type) are NULL for organic installs (~45%).
- `customer_user_id` is ~18% null (NULL pre-login).
- `idfa` is iOS-only and ~40% null (ATT denial); `advertising_id` (GAID) is android-only and ~12% null; `idfv` is iOS-only.
- `media_source` is the raw dirty string for joining to `media_sources`.
- `app_id` differs by platform (`id1565123456` iOS vs `com.nala.app` android).
- `ip` ~5% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| appsflyer_id | text | yes | AppsFlyer device id (PK, device key) |
| customer_user_id | text | yes | `CUS_...` code; NULL pre-login (~18%) |
| install_time | text | no | Naive UTC ISO string (format drift; cast required) |
| attributed_touch_time | text | no | Naive ISO string; NULL for organic |
| attributed_touch_type | text | no | click / impression; NULL for organic |
| media_source | text | no | Raw media source string (dirty join key) |
| campaign | text | no | Free-text campaign name; NULL for organic |
| campaign_id | text | no | Campaign id; NULL for organic |
| af_adset | text | no | Ad set; NULL for organic |
| af_ad | text | no | Ad; NULL for organic |
| af_channel | text | no | Channel (Social/Search/Video); NULL for organic |
| platform | text | no | ios / android |
| app_id | text | no | Bundle/app id (differs by platform) |
| app_version | text | no | App build |
| device_model | text | no | e.g. `iPhone15,3`, `Pixel 8` |
| os_version | text | no | OS version |
| country_code | text | no | ISO-2 country |
| language | text | no | Language/locale |
| idfa | text | yes | iOS advertising id; ~40% null (ATT), null off-iOS |
| idfv | text | yes | iOS vendor id; null off-iOS |
| advertising_id | text | yes | Android GAID; ~12% null, null off-android |
| ip | inet | yes | Client IP (~5% null) |
| is_organic | boolean | no | Whether the install was organic |
| is_retargeting | boolean | no | Whether attributed to a retargeting campaign (~8%) |
| is_primary_attribution | boolean | no | Whether this is the primary attribution record |

## Joins / lineage
- `appsflyer_id` → `raw_appsflyer.in_app_events.appsflyer_id` and `attributions.appsflyer_id` (stable per-customer device key; some IAE orphans).
- `customer_user_id` = customer code → `common.customer_master` (NULL pre-login).
- `media_source` → `raw_appsflyer.media_sources.media_source` (dirty join).
