# raw_onfido.applicants

**Source system:** Onfido (identity-verification / KYC vendor)
**Grain:** one row per Onfido applicant (maps 1:1 to a NALA customer)
**Approx rows (demo scale):** ~60,000 (one per customer)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The Onfido applicant object — the person NALA submitted for identity verification during KYC onboarding. Each applicant holds the identity details (name, dob, address, contact, document numbers) that Onfido runs checks and reports against. It is the anchor for the entire Onfido object graph and joins back to NALA's customer master via `external_id`.

## Known data-quality quirks
- `external_id` (the customer-code join key) is NULL on ~10% of legacy applicants.
- `nala_customer_uuid` was added in a later API version, so it is sparse (~45% null).
- `email` is dirtied (casing/whitespace drift vs core) and ~5% null; `last_name` ~3% null.
- `phone_number` is dirtied E.164 and ~15% null.
- `id_numbers` is a vendor jsonb blob present on only ~40% of rows; it stores `value_last4` only (governed PII-minimisation, never the full number).
- `created_at` is an ISO-8601 string (text), not a timestamp.
- ~2% are sandbox/test applicants (`sandbox=true`); ~1% are soft-deleted (`is_deleted=true`, `deleted_at` always NULL in demo data).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "applicant_<uuid>" |
| external_id | text | no | NALA customer code CUS_... (join key; ~10% null) |
| nala_customer_uuid | text | no | canonical customer uuid (sparse, ~45% null) |
| first_name | text | yes | applicant first name |
| last_name | text | yes | applicant last name (~3% null) |
| email | text | yes | contact email (dirtied; ~5% null) |
| dob | date | yes | date of birth |
| address_line1 | text | yes | street address |
| address_town | text | yes | town/city |
| address_postcode | text | yes | postcode |
| address_country | text | no | ISO-2 country code |
| phone_number | text | yes | dirtied E.164 phone (~15% null) |
| id_numbers | jsonb | yes | vendor blob [{type, value_last4}] (~40% present, last4 only) |
| created_at | text | no | ISO-8601 string |
| href | text | no | vendor self-link |
| sandbox | boolean | no | test-applicant flag (~2%) |
| is_deleted | boolean | no | soft-delete flag (~1%) |
| deleted_at | text | no | soft-delete timestamp (always null in demo) |

## Joins / lineage
- `external_id` = NALA customer code -> customer_master / raw_core_transfers customer code.
- `nala_customer_uuid` -> canonical customer uuid (alt join key).
- `id` <- raw_onfido.checks.applicant_id, reports.applicant_id, documents.applicant_id, facial_similarity_reports.applicant_id, watchlist_reports.applicant_id.
