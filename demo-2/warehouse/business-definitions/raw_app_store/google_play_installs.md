# raw_app_store.google_play_installs

**Source system:** Google Play Console (Reporting — install statistics)
**Grain:** one row per (stat_date, country, app_version_code)
**Approx rows (demo scale):** ~166,000 (`N["events"]` / 30)
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Daily aggregated Android install metrics from the Play Console: daily device installs/uninstalls, daily user installs, active device installs, and store-listing visitors, sliced by country and version code. The Android counterpart to `apple_downloads`; used for install-funnel and retention-by-version analysis.

## Known data-quality quirks
- Uses Google Play's own column semantics: numeric `app_version_code` (not a semver string); `daily_device_installs` vs `daily_user_installs` distinction.
- Aggregated daily metrics — no user id, no PII.
- `loaded_at` ~10% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| row_id | bigint | no | PK. |
| stat_date | date | no | Report day (Google 'Date'). |
| package_name | text | no | 'com.nala.app'. |
| app_version_code | integer | no | Numeric Play version code. |
| country | text | no | ISO-2 (Google 'Country'). |
| daily_device_installs | integer | no | New device installs that day. |
| daily_device_uninstalls | integer | no | Uninstalls that day. |
| daily_user_installs | integer | no | New user installs that day. |
| active_device_installs | integer | no | Active install base. |
| store_listing_visitors | integer | no | Listing visitors. |
| loaded_at | timestamptz | no | Warehouse write time; ~10% null. |

## Joins / lineage
- No customer key; join temporally/geographically (stat_date, country). No staging model.
