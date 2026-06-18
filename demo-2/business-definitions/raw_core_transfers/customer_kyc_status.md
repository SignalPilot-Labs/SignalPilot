# raw_core_transfers.customer_kyc_status

**Source system:** internal core product DB (Postgres)
**Grain:** one row per customer KYC decision (one current row per customer at demo scale)
**Approx rows (demo scale):** ~60,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The KYC / identity-verification outcome for each sending customer, attributed to a verification provider (Onfido / Jumio / Persona). Captures tier, status, risk rating, and the identity document used.

## Known data-quality quirks
- `status` is free text and includes the legacy enum `PENDING_OLD` alongside `approved`/`pending`/`rejected`.
- `submitted_at` is an ISO **string** (text), not a timestamptz; `decided_at` IS a proper timestamptz — mixed types within one table.
- `document_number` is PII and ~8% null.
- `is_current` is always true in demo data (no superseded history rows generated).
- `tier` here is independent of customers.kyc_tier and may disagree.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| kyc_status_id | bigint | no | Primary key |
| customer_id | bigint | no | -> customers.customer_id |
| provider | text | no | KYC provider (Onfido/Jumio/Persona) |
| tier | text | no | tier0/tier1/tier2/tier3 |
| status | text | no | approved/pending/rejected/PENDING_OLD |
| risk_rating | text | no | low/medium/high |
| submitted_at | text | no | ISO string timestamp (not tz) |
| decided_at | timestamptz | no | Decision time |
| document_type | text | no | passport / national_id / drivers_license |
| document_number | text | yes | Identity document number (~8% null) |
| is_current | boolean | no | Current-record flag (always true in demo) |

## Joins / lineage
- `customer_id` -> customers.customer_id.
