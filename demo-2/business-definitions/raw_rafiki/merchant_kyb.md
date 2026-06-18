# raw_rafiki.merchant_kyb

**Source system:** Rafiki compliance service (Onfido / Persona / internal)
**Grain:** one row per merchant KYB case
**Approx rows (demo scale):** ~1,200 (40 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Know-Your-Business verification record for each merchant: legal entity details,
registration/tax identifiers, beneficial-owner info, risk rating and approval
status. Underpins Rafiki's licensed-bridge compliance posture.

## Known data-quality quirks
- `verified_at` is an ISO-Z string, null until `kyb_status = 'approved'`.
- `tax_id` ~10% null.
- `beneficial_owner_dob` stored as ISO date string.
- Merchants with `status = 'PENDING_KYB'` have pending/review/rejected KYB.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| kyb_id | text | no | PK |
| merchant_id | text | no | Owning merchant |
| legal_entity_name | text | no | Legal entity |
| registration_number | text | yes | Company registration no |
| tax_id | text | yes | Tax identifier (sparse) |
| incorporation_country | text | no | Country of incorporation |
| incorporation_date | date | no | Incorporation date |
| beneficial_owner_name | text | yes | UBO name |
| beneficial_owner_dob | text | yes | UBO DOB (ISO string) |
| risk_rating | text | no | low/medium/high |
| kyb_status | text | no | approved/pending/rejected/review |
| provider | text | no | Onfido/Persona/internal |
| verified_at | text | no | ISO-Z string (null until approved) |
| documents | jsonb | no | Doc references |
| created_at | timestamptz | no | Case open time |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`.
