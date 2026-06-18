# raw_app_store.google_play_installs

**Source system:** Google Play
**Grain:** one row per (stat_date, country, app_version_code)
**Approx rows (demo scale):** ~166,000
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Daily aggregated install statistics from Google Play Console (Reporting). Android counterpart to `apple_downloads`, driving Android store-funnel reporting: store listing visitors, daily device installs/uninstalls, and active install base by country and version code.

## Known data-quality quirks
- Aggregated daily metrics — no user id and no customer join key.
- Uses Google's numeric `app_version_code` (e.g. 341, 420), not the human version name used by Apple/AppsFlyer.
- `loaded_at` is ~10% null.
- Date coverage is downsampled at generation (stepped dates).
- Column naming follows Google Play report headers (Daily Device Installs, Active Device Installs, etc.).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| row_id | bigint | no | Surrogate row id (PK) |
| stat_date | date | no | Report date (Google: 'Date') |
| package_name | text | no | `com.nala.app` |
| app_version_code | integer | no | Numeric Android version code |
| country | text | no | ISO-2 country (Google: 'Country') |
| daily_device_installs | integer | no | First-time device installs that day |
| daily_device_uninstalls | integer | no | Device uninstalls that day |
| daily_user_installs | integer | no | User installs that day |
| active_device_installs | integer | no | Active install base |
| store_listing_visitors | integer | no | Store listing visitors |
| loaded_at | timestamptz | no | Warehouse write time (~10% null) |

## Joins / lineage
- No customer-level join (anonymous aggregate). Joins temporally/geographically on (`stat_date`, `country`) into marketing / install funnels.
