# raw_onfido.documents

**Source system:** Onfido (KYC)
**Grain:** one row per uploaded identity document
**Approx rows (demo scale):** ~70k
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The identity documents (passport, driving licence, national id, residence permit)
a customer uploaded for verification, with the parsed printed fields. PII is
GOVERNED: the document number is never stored in full — only `document_number_last4`
plus `document_number_hash` (sha256) are retained, mimicking real PII minimisation.

## Known data-quality quirks
- Full document number is intentionally NOT stored (governance) — only last4 + hash.
- `issuing_country` uses ISO-3 (GBR, KEN) the Onfido way, unlike applicants (ISO-2).
- `side` is null for passports; `expiry_date` ~20% null.
- `created_at` is an ISO-8601 string.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | document id ("doc_<uuid>"), PK |
| applicant_id | text | no | -> applicants.id |
| type | text | no | passport / driving_licence / national_identity_card / residence_permit |
| side | text | no | front / back / NULL (passports) |
| issuing_country | text | no | ISO-3 issuing country |
| document_number_last4 | text | yes | last 4 of doc number (governed) |
| document_number_hash | text | yes | sha256 of full doc number (governed) |
| first_name | text | yes | name as printed on doc |
| last_name | text | yes | name as printed on doc |
| dob | date | yes | dob as printed on doc |
| expiry_date | date | no | document expiry (~20% null) |
| file_name | text | no | uploaded file name |
| file_type | text | no | mime type |
| file_size | integer | no | bytes |
| download_href | text | no | vendor download link |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- Joins to `raw_onfido.applicants` on `applicant_id`.
- Referenced by `raw_onfido.reports.documents` jsonb.
- `document_number_hash` enables governed cross-system matching without exposing the PAN.
