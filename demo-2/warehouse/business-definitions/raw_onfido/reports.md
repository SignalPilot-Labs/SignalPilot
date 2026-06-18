# raw_onfido.reports

**Source system:** Onfido (KYC)
**Grain:** one row per report (the unit Onfido adjudicates)
**Approx rows (demo scale):** ~70k (the document report per check)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
A report is the atomic adjudication unit inside a check. This table holds the
generic/document reports; the specialised facial-similarity and watchlist variants
live in their own tables but share the `rep_<uuid>` id space.

## Known data-quality quirks
- `created_at`/`completed_at` are ISO-8601 strings; `completed_at` null while running.
- `result`/`sub_result` null for in-progress reports.
- `breakdown`, `properties`, `documents` are vendor jsonb blobs.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | report id ("rep_<uuid>"), PK |
| check_id | text | no | -> checks.id |
| applicant_id | text | no | denormalised -> applicants.id |
| name | text | no | report type (document, identity_enhanced, ...) |
| status | text | no | awaiting_data / awaiting_approval / complete / withdrawn / cancelled |
| result | text | no | clear / consider / unidentified / NULL |
| sub_result | text | no | clear / rejected / suspected / caution |
| breakdown | jsonb | no | nested breakdown blob |
| properties | jsonb | yes | extracted document fields blob |
| documents | jsonb | no | referenced document ids |
| created_at | text | no | ISO-8601 string |
| completed_at | text | no | ISO string; null while running |
| href | text | no | vendor self-link |

## Joins / lineage
- Joins to `raw_onfido.checks` on `check_id`, `raw_onfido.applicants` on `applicant_id`.
- `documents` jsonb references `raw_onfido.documents.id`.
