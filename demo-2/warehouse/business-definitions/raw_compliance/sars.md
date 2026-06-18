# raw_compliance.sars

**Source system:** NALA internal compliance system (MLRO team source of record)
**Grain:** one row per Suspicious Activity Report (filed or drafted)
**Approx rows (demo scale):** ~1.5k
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
SARs are the formal reports NALA's MLRO files to regulators/FIUs (FCA, FinCEN,
FINTRAC, CBN, BoU) when a customer's activity is judged suspicious. Filed for the
highest-risk cases. PII is GOVERNED: the subject national id is stored as
subject_national_id plus subject_national_id_hash (sha256).

## Known data-quality quirks
- This is OUR system: timestamps are clean tz-aware timestamptz.
- status carries legacy value 'SUBMITTED' on older rows (vs 'filed').
- filed_at / filing_reference null while in draft.
- transfer_id references the triggering transfer but is ~40% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| sar_id | bigint | no | PK |
| sar_ref | text | no | human ref (SAR-2025-000123) |
| customer_code | text | no | CUS_00000123 (join key) |
| customer_uuid | uuid | no | canonical customer uuid (alt join key) |
| subject_name | text | yes | subject of the report |
| subject_national_id | text | yes | national id (governed, kept for filing) |
| subject_national_id_hash | text | yes | sha256 of national id (governed lookup) |
| transfer_id | uuid | no | triggering transfer (-> core transfers; ~40% null) |
| activity_type | text | no | structuring / rapid_movement / sanctions_hit / ... |
| status | text | no | draft / filed / acknowledged / closed_no_action (legacy SUBMITTED) |
| priority | text | no | low / medium / high / critical |
| regulator | text | no | FCA / FINTRAC / FinCEN / CBN / BoU |
| filing_reference | text | no | regulator reference once acknowledged |
| narrative | text | yes | free-text investigator narrative |
| amount_usd | numeric(20,2) | no | aggregate suspicious amount |
| filed_by | text | no | MLRO/analyst id |
| filed_at | timestamptz | no | filing time; null while draft |
| created_at | timestamptz | no | row creation |
| updated_at | timestamptz | no | last update |

## Joins / lineage
- Joins to NALA core customers on customer_code = customers.code (or customer_uuid).
- transfer_id -> raw_core_transfers.transfers.transfer_id (det_uuid("transfer", i)).
