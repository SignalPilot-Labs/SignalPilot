# raw_onfido.facial_similarity_reports

**Source system:** Onfido (KYC)
**Grain:** one row per facial-similarity (selfie vs document) report
**Approx rows (demo scale):** ~70k
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The liveness/face-match report comparing the customer's selfie against the photo on
their identity document. Drives the biometric leg of KYC.

## Known data-quality quirks
- `score` (0..1 match score) is ~25% null (older variants didn't return it).
- `result`/`sub_result` follow Onfido's clear/consider/rejected/suspected/caution.
- `completed_at` null while the parent check is still running.
- jsonb blobs (`face_comparison`, `image_integrity`, `visual_authenticity`) are raw.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | report id ("rep_<uuid>"), PK |
| check_id | text | no | -> checks.id |
| applicant_id | text | no | -> applicants.id |
| variant | text | no | standard / video / motion |
| result | text | no | clear / consider |
| sub_result | text | no | clear / rejected / suspected / caution |
| score | numeric(5,4) | no | 0..1 face match score (~25% null) |
| face_comparison | jsonb | no | breakdown blob |
| image_integrity | jsonb | no | breakdown blob |
| visual_authenticity | jsonb | no | breakdown blob |
| created_at | text | no | ISO-8601 string |
| completed_at | text | no | ISO string; null while running |

## Joins / lineage
- Joins to `raw_onfido.checks` on `check_id`, `raw_onfido.applicants` on `applicant_id`.
