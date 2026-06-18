# raw_chainalysis.screening_alerts

**Source system:** Chainalysis (crypto wallet risk screening)
**Grain:** one row per alert raised off a high-risk screening
**Approx rows (demo scale):** ~2,400 (only High/Severe screenings, ~10% of all screenings, raise an alert)
**Loaded by:** warehouse/generators/gen_raw_chainalysis.py

## Business definition
An alert raised when a wallet screening comes back High or Severe risk. It captures the risk category, attributed service, the USD exposure that triggered it, and the analyst lifecycle (OPEN -> IN_REVIEW -> DISMISSED/CONFIRMED). These are the crypto-compliance work items the MLRO team investigates and which can spawn a compliance case or SAR.

## Known data-quality quirks
- Sparse: only High/Severe screenings emit alerts.
- `triggered_at_epoch_ms` is stored as epoch MILLISECONDS (bigint) — a deliberate format drift from the ISO-8601 string `created_at`.
- `disposition` (analyst free text) is ~50% null.
- `status` skews DISMISSED (~40%) with OPEN/IN_REVIEW/CONFIRMED in the rest.
- `address` is denormalised from the parent screening (PII).
- `exposure_usd`/`alert_amount_usd` are numeric(20,2) USD.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "alrt_<uuid>" |
| screening_id | text | no | -> address_screenings.id |
| address | text | yes | denormalised wallet address (PII) |
| alert_level | text | no | High / Severe |
| category | text | no | sanctions / darknet / scam / stolen funds / terrorist financing |
| service | text | no | attributed service / cluster name |
| exposure_type | text | no | DIRECT / INDIRECT |
| exposure_usd | numeric(20,2) | no | USD value of exposure that triggered the alert |
| alert_amount_usd | numeric(20,2) | no | USD alert amount |
| triggered_at_epoch_ms | bigint | no | epoch MILLISECONDS at trigger (format drift) |
| status | text | no | OPEN / IN_REVIEW / DISMISSED / CONFIRMED |
| disposition | text | no | analyst disposition free text (~50% null) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `screening_id` -> raw_chainalysis.address_screenings.id.
