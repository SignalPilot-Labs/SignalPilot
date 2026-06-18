# raw_app_store.apple_downloads

**Source system:** Apple App Store
**Grain:** one row per (report_date, country, app_version, source_type, device)
**Approx rows (demo scale):** ~166,000
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Daily aggregated download and units metrics from App Store Connect Analytics. Drives top-of-funnel store performance reporting (impressions → product page views → first-time downloads) for the iOS app, broken out by storefront, version, source, and device.

## Known data-quality quirks
- Fully aggregated daily metrics — no user id and no customer join key.
- `source_type` includes an `Unavailable` bucket (Apple privacy masking).
- `loaded_at` is ~10% null.
- Date coverage is downsampled at generation (stepped dates, not every calendar day).
- Counts are independent random draws — `redownloads`/`updates`/`impressions` are not guaranteed internally consistent with `units` beyond rough scaling.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| row_id | bigint | no | Surrogate row id (PK) |
| report_date | date | no | Report date |
| app_version | text | no | App version string |
| country_code | text | no | ISO-2 storefront |
| source_type | text | no | App Store Search / App Referrer / Web Referrer / Browse / Unavailable |
| device | text | no | iPhone / iPad |
| units | integer | no | First-time downloads |
| redownloads | integer | no | Redownloads |
| updates | integer | no | App updates |
| impressions | integer | no | Store impressions |
| product_page_views | integer | no | Product page views |
| loaded_at | timestamptz | no | Warehouse write time (~10% null) |

## Joins / lineage
- No customer-level join (anonymous aggregate). Joins temporally/geographically on (`report_date`, `country_code`) into marketing / install funnels.
