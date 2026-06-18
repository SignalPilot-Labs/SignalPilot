# raw_compliance.sars

**Source system:** internal NALA compliance operations (MLRO regulatory filing)
**Grain:** one row per Suspicious Activity Report filed (or drafted) to a regulator/FIU
**Approx rows (demo scale):** ~1,500 (filed only for the worst case resolutions / prohibited-risk customers)
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
A Suspicious Activity Report drafted or filed by NALA's MLRO team to a financial regulator/FIU (FCA, FINTRAC, FinCEN, CBN, BoU). It records the subject, the suspicious `activity_type`, the aggregate suspicious amount, the investigator narrative, and the filing lifecycle from draft to acknowledged. This is the heaviest-PII internal table, so the subject's national ID is governed (`subject_national_id` + `subject_national_id_hash`).

## Known data-quality quirks
- `status` carries a legacy value `SUBMITTED` on ~30% of pre-2022 filed rows; modern rows use draft/filed/acknowledged/closed_no_action.
- `filed_at` is NULL while the SAR is a draft; `filing_reference` is NULL until the regulator acknowledges.
- `transfer_id` (the triggering transfer) is sparse (~60% populated).
- National ID governed: `subject_national_id` kept for filing (PII) plus `subject_national_id_hash` (sha256 lookup key).
- `narrative` is free-text investigator PII.
- Internal system: `filed_at`/`created_at`/`updated_at` are clean tz-aware `timestamptz`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| sar_id | bigint | no | PK |
| sar_ref | text | no | human ref SAR-YYYY-###### |
| customer_code | text | no | CUS_... (join key) |
| customer_uuid | uuid | no | canonical customer uuid (alt join key) |
| subject_name | text | yes | subject of the report |
| subject_national_id | text | yes | national id kept for filing (governed) |
| subject_national_id_hash | text | yes | sha256 of national id (governed lookup key) |
| transfer_id | uuid | no | triggering transfer (~60% populated) |
| activity_type | text | no | structuring / rapid_movement / sanctions_hit / third_party / fraud / mule_account |
| status | text | no | draft / filed / acknowledged / closed_no_action; legacy SUBMITTED |
| priority | text | no | low / medium / high / critical |
| regulator | text | no | FCA / FINTRAC / FinCEN / CBN / BoU |
| filing_reference | text | no | regulator reference once acknowledged; null until then |
| narrative | text | yes | free-text investigator narrative |
| amount_usd | numeric(20,2) | no | aggregate suspicious amount |
| filed_by | text | no | MLRO / analyst id |
| filed_at | timestamptz | no | filing time; null while draft |
| created_at | timestamptz | no | row insert time |
| updated_at | timestamptz | no | last update time |

## Joins / lineage
- `customer_code` / `customer_uuid` -> customer_master.
- `transfer_id` -> raw_core_transfers.transfers.transfer_id.
