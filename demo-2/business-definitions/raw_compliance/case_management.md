# raw_compliance.case_management

**Source system:** internal NALA compliance operations (case-management queue)
**Grain:** one row per compliance case (an investigation; may or may not become a SAR)
**Approx rows (demo scale):** ~8,000 (raised mostly off high/prohibited-risk customers; ~20% get a second case)
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
A compliance investigation case in NALA's internal queue. Cases are raised from KYC/AML/crypto/rules signals (the `source` + `source_ref` point back to the originating system) and worked through a triage -> investigation -> MLRO queue lifecycle with SLA tracking. Higher-risk customers are far more likely to have a case; `resolution` records the outcome and whether it escalated to a SAR.

## Known data-quality quirks
- `status` carries a legacy value `NEW` on ~30% of pre-2022 open cases; modern rows use open/in_progress/pending_info/escalated/closed.
- `resolution` is NULL while the case is open; `closed_at` is NULL while open.
- `assigned_to` is more often null on open cases (~50%) than closed (~15%).
- `source_ref` shape depends on `source` (Onfido check id, ComplyAdvantage search id, Chainalysis screening id, or null for rules_engine/manual).
- `sla_breached` is computed against `sla_due_at` (open cases breach if now > due).
- Internal system: timestamps are clean tz-aware `timestamptz`; `notes` is a jsonb array of timestamped note blobs.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| case_id | bigint | no | PK |
| case_ref | text | no | CASE-YYYY-###### |
| customer_code | text | no | CUS_... (join key) |
| case_type | text | no | kyc_review / aml_alert / sanctions_review / fraud / edd / transaction_monitoring |
| source | text | no | onfido / complyadvantage / chainalysis / rules_engine / manual |
| source_ref | text | no | id in the source system (shape varies by source) |
| status | text | no | open / in_progress / pending_info / escalated / closed; legacy NEW |
| priority | text | no | low / medium / high / critical |
| assigned_to | text | no | analyst id (null if unassigned) |
| queue | text | no | l1_triage / l2_investigation / mlro |
| risk_rating | text | no | low / medium / high |
| resolution | text | no | cleared / sar_filed / account_closed / false_positive / escalated; null while open |
| sla_due_at | timestamptz | no | SLA due time |
| opened_at | timestamptz | no | case open time |
| closed_at | timestamptz | no | close time; null while open |
| sla_breached | boolean | no | SLA breach flag |
| notes | jsonb | yes | array of timestamped note blobs (may contain narrative) |
| created_at | timestamptz | no | row insert time |

## Joins / lineage
- `customer_code` -> customer_master.
- `source_ref` -> raw_onfido.checks.id / raw_complyadvantage.searches.id / raw_chainalysis.address_screenings.id depending on `source`.
