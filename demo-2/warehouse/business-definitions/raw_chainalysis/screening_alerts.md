# raw_chainalysis.screening_alerts

**Source system:** Chainalysis (crypto risk)
**Grain:** one row per alert raised off a high-risk screening
**Approx rows (demo scale):** ~2.5k (only High/Severe screenings)
**Loaded by:** warehouse/generators/gen_raw_chainalysis.py

## Business definition
When a screening returns High or Severe risk, Chainalysis raises an alert quantifying
the risky exposure (USD) and its category. These drive sanctions/crypto compliance
cases and potential SAR filing.

## Known data-quality quirks
- `triggered_at_epoch_ms` is epoch MILLISECONDS while `created_at` is an ISO string.
- `disposition` ~50% null (un-reviewed alerts).
- Only exists for High/Severe parent screenings.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | alert id ("alrt_<uuid>"), PK |
| screening_id | text | no | -> address_screenings.id |
| address | text | yes | denormalised wallet address |
| alert_level | text | no | High / Severe |
| category | text | no | sanctions / darknet / scam / stolen funds / terrorist financing |
| service | text | no | attributed service/cluster name |
| exposure_type | text | no | DIRECT / INDIRECT |
| exposure_usd | numeric(20,2) | no | USD value of risky exposure |
| alert_amount_usd | numeric(20,2) | no | USD amount that triggered the alert |
| triggered_at_epoch_ms | bigint | no | epoch MILLISECONDS |
| status | text | no | OPEN / IN_REVIEW / DISMISSED / CONFIRMED |
| disposition | text | no | analyst disposition (~50% null) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- Joins to `raw_chainalysis.address_screenings` on `screening_id`.
