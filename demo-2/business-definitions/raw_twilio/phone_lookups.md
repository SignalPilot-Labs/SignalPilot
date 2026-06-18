# raw_twilio.phone_lookups

**Source system:** Twilio Lookup v2 API (carrier + line-type intelligence)
**Grain:** one row per phone-number lookup request
**Approx rows (demo scale):** ~750,000 (`N["transfers"] / 4`)
**Loaded by:** warehouse/generators/gen_raw_twilio.py

## Business definition
NALA calls Twilio Lookup during onboarding and high-risk transfer checks to validate a phone number, identify its carrier and line type (mobile vs VOIP), and flag SIM-swap risk. Used by compliance/fraud to score number quality.

## Known data-quality quirks
- `created_epoch_ms` is epoch milliseconds (bigint), not a timestamp.
- `carrier_mcc` / `carrier_mnc` / `sim_swap_risk` are sparse (Lookup add-on data not always purchased).
- `phone_number` is stored clean E.164 here (the lookup normalizes it), unlike `messages.to_number`.
- `validation_errors` only populated when `valid = false`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| lookup_sid | text | no | internal lookup id (PK) |
| phone_number | text | yes | queried number, E.164 |
| national_format | text | yes | national formatting (sparse) |
| country_code | text | no | ISO2 country |
| calling_country_code | text | no | dialing prefix (+44 etc) |
| valid | boolean | no | number validity |
| validation_errors | text | no | error list (sparse) |
| line_type | text | no | mobile/landline/voip/nonFixedVoip |
| carrier_name | text | no | carrier (Safaricom, Vodafone UK…) |
| carrier_mcc | text | no | mobile country code (sparse) |
| carrier_mnc | text | no | mobile network code (sparse) |
| sim_swap_risk | text | no | low/medium/high (sparse) |
| customer_id | bigint | no | resolved canonical cid (sparse) |
| created_epoch_ms | bigint | no | epoch ms timestamp |
| raw_response | jsonb | no | Lookup v2 response blob |

## Joins / lineage
- Joins to canonical customer on `customer_id`, or `phone_number` ↔ `customer_master.phone` (clean here).
