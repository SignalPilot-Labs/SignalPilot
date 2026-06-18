# raw_appsflyer.in_app_events

**Source system:** AppsFlyer (Raw Data — in-app event postbacks)
**Grain:** one row per post-install in-app event
**Approx rows (demo scale):** ~833,000 (`N["events"]` / 6)
**Loaded by:** warehouse/generators/gen_raw_appsflyer.py

## Business definition
Post-install conversion events AppsFlyer tracks for ROI (registration, first transfer, purchase, add-payment-info, login), carrying the AppsFlyer `af_*` event-value JSON and parsed revenue where applicable. Used to tie revenue and key conversions back to acquisition channels.

## Known data-quality quirks
- **`event_time` is a naive UTC ISO *string* (text)** — parse with `to_timestamp(..., 'YYYY-MM-DD HH24:MI:SS')`.
- `customer_user_id` ~30% null.
- `event_revenue` only set for `af_first_transfer`/`af_purchase` (else null); revenue also lives inside `event_value` jsonb.
- Some `appsflyer_id` values are orphans (no matching install row) — realistic late/lost postbacks.
- `ip` ~5% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| event_uuid | text | no | PK. |
| appsflyer_id | text | yes | Device id (→ installs.appsflyer_id; some orphans). |
| customer_user_id | text | yes | Customer code CUS_...; ~30% null. |
| event_name | text | no | af_complete_registration / af_first_transfer / af_purchase / ... |
| event_time | text | no | Naive UTC ISO string. |
| event_value | jsonb | no | af_* event-value JSON ({af_revenue, af_currency, ...}). |
| event_revenue | numeric(18,2) | no | Parsed revenue convenience col; often null. |
| event_revenue_currency | text | no | Revenue currency. |
| media_source / campaign | text | no | Attribution at event time. |
| platform | text | no | ios / android. |
| app_version | text | no | App build. |
| country_code | text | no | ISO-2. |
| ip | inet | yes | Client IP. |

## Joins / lineage
- `appsflyer_id` → `raw_appsflyer.installs.appsflyer_id` (dirty: orphans exist).
- `customer_user_id` → `raw_core_transfers.customers.customer_code`.
- `media_source` → `raw_appsflyer.media_sources.media_source`.
- No staging model (loaded but not a Domain-8 key staging table).
