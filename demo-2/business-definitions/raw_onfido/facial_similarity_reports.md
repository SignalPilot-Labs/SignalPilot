# raw_onfido.facial_similarity_reports

**Source system:** Onfido (identity-verification / KYC vendor)
**Grain:** one row per facial-similarity (selfie vs document) report
**Approx rows (demo scale):** ~71,000 (one per check)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The Onfido facial-similarity report — compares a live selfie (standard/video/motion variant) against the photo on the uploaded identity document to confirm the applicant is the document holder. NALA reads `result`/`sub_result` and the face-match `score` as part of the liveness/biometric leg of KYC.

## Known data-quality quirks
- `score` (0..1 face-match score) is sparse (~25% null), even on completed reports.
- `result` skews clean: ~92% clear, ~8% consider.
- `sub_result` is `clear` when result is clear, otherwise suspected/caution.
- `created_at` is an ISO string; `completed_at` is ISO and NULL while the parent check is still running.
- `face_comparison`, `image_integrity`, `visual_authenticity` are vendor jsonb breakdown blobs.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "rep_<uuid>" |
| check_id | text | no | -> checks.id |
| applicant_id | text | no | -> applicants.id |
| variant | text | no | standard / video / motion |
| result | text | no | clear / consider |
| sub_result | text | no | clear / rejected / suspected / caution |
| score | numeric(5,4) | no | 0..1 face-match score (~25% null) |
| face_comparison | jsonb | yes | face-match breakdown blob (biometric) |
| image_integrity | jsonb | no | image-integrity breakdown blob |
| visual_authenticity | jsonb | no | visual-authenticity breakdown blob |
| created_at | text | no | ISO-8601 string |
| completed_at | text | no | ISO string; null while running |

## Joins / lineage
- `check_id` -> raw_onfido.checks.id.
- `applicant_id` -> raw_onfido.applicants.id.
