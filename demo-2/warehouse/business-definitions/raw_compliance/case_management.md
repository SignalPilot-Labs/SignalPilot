# raw_compliance.case_management

**Source system:** NALA internal compliance system
**Grain:** one row per compliance case (an investigation)
**Approx rows (demo scale):** ~9k
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
The investigation queue. A case is opened when a signal (Onfido check, ComplyAdvantage
alert, Chainalysis screening, a rules-engine flag, or manual referral) needs human
review. Cases may close as cleared/false-positive or escalate to a SAR.

## Known data-quality quirks
- status carries legacy value 'NEW' on older rows (vs 'open').
- source_ref points into the originating system (Onfido check id, ComplyAdvantage
  search id, Chainalysis screening id) - cross-system but NOT FK-enforced.
- resolution / closed_at null while open; assigned_to null if unassigned.
- notes is a jsonb array of timestamped note blobs.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| case_id | bigint | no | PK |
| case_ref | text | no | CASE-2025-000123 |
| customer_code | text | no | CUS_00000123 (join key) |
| case_type | text | no | kyc_review / aml_alert / sanctions_review / fraud / edd / transaction_monitoring |
| source | text | no | onfido / complyadvantage / chainalysis / rules_engine / manual |
| source_ref | text | no | id in the originating source system |
| status | text | no | open / in_progress / pending_info / escalated / closed (legacy NEW) |
| priority | text | no | low / medium / high / critical |
| assigned_to | text | no | analyst id (null if unassigned) |
| queue | text | no | l1_triage / l2_investigation / mlro |
| risk_rating | text | no | low / medium / high |
| resolution | text | no | cleared / sar_filed / account_closed / false_positive / escalated |
| sla_due_at | timestamptz | no | SLA deadline |
| opened_at | timestamptz | no | case open time |
| closed_at | timestamptz | no | close time; null while open |
| sla_breached | boolean | no | SLA breach flag |
| notes | jsonb | no | timestamped note array |
| created_at | timestamptz | no | row creation |

## Joins / lineage
- Joins to NALA core customers on customer_code.
- source_ref cross-references Onfido / ComplyAdvantage / Chainalysis (dirty, not FK).
