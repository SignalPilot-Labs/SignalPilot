# raw_appsflyer.in_app_events

**Source system:** AppsFlyer
**Grain:** one row per post-install in-app event tracked by AppsFlyer
**Approx rows (demo scale):** ~833,000
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
AppsFlyer post-install events used for ROI / ROAS measurement (registration, first transfer, purchase, add-payment, login). Carries the AppsFlyer `af_*` event-value payload and parsed revenue so paid-acquisition spend can be tied to downstream monetization per media source and campaign.

## Known data-quality quirks
- `event_time` is a naive UTC ISO **string** (text), vendor format drift — cast before time math.
- `appsflyer_id` references `installs.appsflyer_id` but some rows are orphans (no matching install).
- `customer_user_id` is ~30% null.
- `event_revenue` / `event_revenue_currency` are only populated for `af_first_transfer` and `af_purchase`; null for non-revenue events.
- `event_value` jsonb is the raw `af_*` payload (e.g. {af_revenue, af_currency, af_content_type}).
- `media_source` is attribution at event time (dirty free-text); `ip` ~5% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| event_uuid | text | no | Event uuid (PK) |
| appsflyer_id | text | yes | → installs.appsflyer_id (device key; some orphans) |
| customer_user_id | text | yes | `CUS_...` code; ~30% null |
| event_name | text | no | af_complete_registration / af_first_transfer / af_purchase / ... |
| event_time | text | no | Naive UTC ISO string (format drift; cast required) |
| event_value | jsonb | no | Raw af_* payload ({af_revenue, af_currency, ...}) |
| event_revenue | numeric(18,2) | no | Parsed revenue (only for transfer/purchase events) |
| event_revenue_currency | text | no | Revenue currency (null for non-revenue events) |
| media_source | text | no | Attribution media source at event time (dirty) |
| campaign | text | no | Campaign name; null for organic |
| platform | text | no | ios / android |
| app_version | text | no | App build |
| country_code | text | no | ISO-2 country |
| ip | inet | yes | Client IP (~5% null) |

## Joins / lineage
- `appsflyer_id` → `raw_appsflyer.installs.appsflyer_id` (expect some orphans).
- `customer_user_id` = customer code → `common.customer_master`.
- `media_source` → `raw_appsflyer.media_sources.media_source` (dirty join).
