# raw_onfido.documents

**Source system:** Onfido (identity-verification / KYC vendor)
**Grain:** one row per uploaded identity document
**Approx rows (demo scale):** ~71,000 (one document per check)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The identity document an applicant uploaded for verification (passport, driving licence, national ID card, residence permit). Holds the printed identity fields and file metadata that Onfido's document report adjudicates against. This is the heaviest-PII table in the schema, so the document number is governed: only the last 4 digits plus a sha256 hash of the full number are retained.

## Known data-quality quirks
- Document number is governed: `document_number_last4` + `document_number_hash` (sha256) only — the full number is never stored.
- `side` is NULL for passports; `front`/`back`/NULL for other doc types.
- `issuing_country` is ISO-3 (the Onfido way, e.g. GBR, KEN), unlike applicants.address_country which is ISO-2.
- `expiry_date` ~20% null.
- `first_name`/`last_name`/`dob` are copied as printed on the document and may drift from the applicant record.
- `created_at` is an ISO-8601 string (text).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "doc_<uuid>" |
| applicant_id | text | no | -> applicants.id |
| type | text | no | passport / driving_licence / national_identity_card / residence_permit |
| side | text | no | front / back / NULL (null for passports) |
| issuing_country | text | no | ISO-3 issuing country |
| document_number_last4 | text | yes | last 4 of document number (governed) |
| document_number_hash | text | yes | sha256 of full document number (governed) |
| first_name | text | yes | name as printed on the document |
| last_name | text | yes | name as printed on the document |
| dob | date | yes | date of birth as printed on the document |
| expiry_date | date | no | document expiry (~20% null) |
| file_name | text | no | uploaded file name |
| file_type | text | no | MIME type (image/jpeg) |
| file_size | integer | no | file size in bytes |
| download_href | text | no | vendor download link |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `applicant_id` -> raw_onfido.applicants.id.
- `id` referenced by raw_onfido.reports.documents[] array.
