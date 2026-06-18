# raw_onfido.reports

**Source system:** Onfido (identity-verification / KYC vendor)
**Grain:** one row per Onfido report (the unit Onfido actually adjudicates)
**Approx rows (demo scale):** ~71,000 document reports (one document report per check; facial_similarity and watchlist live in their own tables)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The Onfido report object — the adjudicated unit inside a check. In this warehouse the generic `reports` table holds the `document` report (authenticity/validity of the uploaded ID), while facial-similarity and watchlist variants are split into their dedicated tables. The `result`/`sub_result` pair is what NALA reads to know whether the identity document passed, and the nested `breakdown`/`properties` blobs carry the parsed evidence.

## Known data-quality quirks
- `result` is NULL while a report is running; `document` reports map `clear`/`consider` from the `sub_result`.
- `sub_result` distribution is skewed clean: ~88% clear, with rejected/suspected/caution in the tail.
- `created_at` is an ISO-8601 string; `completed_at` is ISO and NULL while running.
- `breakdown`, `properties`, `documents` are vendor jsonb blobs (`documents` is an array of referenced doc ids).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "rep_<uuid>" |
| check_id | text | no | -> checks.id |
| applicant_id | text | no | denormalised -> applicants.id |
| name | text | no | report type (document / facial_similarity_photo / watchlist_standard / identity_enhanced ...) |
| status | text | no | awaiting_data / awaiting_approval / complete / withdrawn / cancelled |
| result | text | no | clear / consider / unidentified / NULL |
| sub_result | text | no | document-report disposition: clear / rejected / suspected / caution |
| breakdown | jsonb | no | nested vendor breakdown blob |
| properties | jsonb | yes | extracted/parsed doc-field blob (may contain identity fields) |
| documents | jsonb | no | array of referenced document ids |
| created_at | text | no | ISO-8601 string |
| completed_at | text | no | ISO string; null while running |
| href | text | no | vendor self-link |

## Joins / lineage
- `check_id` -> raw_onfido.checks.id.
- `applicant_id` -> raw_onfido.applicants.id.
- `documents[]` -> raw_onfido.documents.id.
