# raw_onfido.applicants

**Source system:** Onfido (KYC identity-verification vendor)
**Grain:** one row per Onfido applicant (1:1 with a NALA customer)
**Approx rows (demo scale):** ~60k (one per customer)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
An Onfido "applicant" is the identity record NALA creates for each customer before
running KYC checks. It holds the PII Onfido needs to verify a person (name, dob,
address, contact). Every NALA customer maps to exactly one applicant; the
`external_id` carries the NALA customer code so the two systems can be joined.

## Known data-quality quirks
- `created_at` is an ISO-8601 string (text), not a timestamp.
- ~10% of (legacy) applicants have a null `external_id` — identity resolution must
  then fall back to email/name/dob matching.
- `nala_customer_uuid` was added in a later API version: ~45% null.
- `email` runs through `dirty_email` (casing/dot/leading-space drift vs core).
- `phone_number` runs through `dirty_phone` (format drift); ~15% null.
- `id_numbers` is a sparse vendor jsonb blob; ~60% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | Onfido applicant id ("applicant_<uuid>"), PK |
| external_id | text | no | NALA customer code (CUS_00000123); the join key, ~10% null |
| nala_customer_uuid | text | no | canonical customer uuid; sparse (newer rows only) |
| first_name | text | yes | given name |
| last_name | text | yes | family name (~3% null) |
| email | text | yes | contact email, dirtied casing/format |
| dob | date | yes | date of birth |
| address_line1 | text | yes | street address |
| address_town | text | yes | town/city |
| address_postcode | text | yes | postcode |
| address_country | text | no | ISO-2 country |
| phone_number | text | yes | E.164-ish phone, dirtied format |
| id_numbers | jsonb | yes | vendor blob, only document number last4 retained |
| created_at | text | no | ISO-8601 string timestamp |
| href | text | no | vendor self-link |
| sandbox | boolean | no | test applicant flag (~2%) |
| is_deleted | boolean | no | soft-delete flag |
| deleted_at | text | no | soft-delete timestamp (ISO string) |

## Joins / lineage
- Joins to NALA core customers on `external_id = customers.code` (dirty: ~10% null).
- Alt join on `nala_customer_uuid` where present.
- 1:N to `raw_onfido.checks` on `applicants.id = checks.applicant_id`.
