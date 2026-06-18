# raw_app_store.apple_downloads

**Source system:** Apple App Store Connect (Analytics — sales/units report)
**Grain:** one row per (report_date, country, app_version, source_type, device)
**Approx rows (demo scale):** ~166,000 (`N["events"]` / 30)
**Loaded by:** warehouse/generators/gen_raw_app_store.py

## Business definition
Daily aggregated iOS download and discovery metrics from App Store Connect: first-time units, redownloads, updates, impressions, and product-page views, sliced by storefront country, app version, traffic source, and device. Used for organic-vs-paid install analysis and store-listing conversion (impression → page view → download).

## Known data-quality quirks
- Aggregated daily metrics — no user id, no PII.
- `loaded_at` ~10% null.
- `source_type` includes Apple's catch-all 'Unavailable'.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| row_id | bigint | no | PK. |
| report_date | date | no | Report day. |
| app_version | text | no | App build. |
| country_code | text | no | Storefront ISO-2. |
| source_type | text | no | App Store Search / App Referrer / Web Referrer / Browse / Unavailable. |
| device | text | no | iPhone / iPad. |
| units | integer | no | First-time downloads. |
| redownloads | integer | no | Redownloads. |
| updates | integer | no | App updates. |
| impressions | integer | no | Store impressions. |
| product_page_views | integer | no | Product page views. |
| loaded_at | timestamptz | no | Warehouse write time; ~10% null. |

## Joins / lineage
- No customer key; join temporally/geographically (report_date, country_code) into install funnels. No staging model.
