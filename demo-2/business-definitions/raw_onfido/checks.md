# raw_onfido.checks

**Source system:** Onfido (identity-verification / KYC vendor)
**Grain:** one row per Onfido check (a check groups one or more reports)
**Approx rows (demo scale):** ~71,000 (1 onboarding check per applicant + ~18% re-verification)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The Onfido check object — a verification run requested for an applicant that bundles one or more reports (document, facial_similarity, watchlist). The check `result` is the overall adjudication NALA reads to decide whether to clear or escalate a customer at onboarding (and at re-verification). Most applicants have a single onboarding check; ~18% carry an extra re-verification check.

## Known data-quality quirks
- `result` carries legacy uppercase `PASS`/`FAIL` on ~30% of pre-2021 rows (modern rows use `clear`/`consider`/NULL).
- `result` is NULL while a check is still running (`in_progress`) or `withdrawn`.
- `completed_at_epoch` is stored as epoch SECONDS (bigint) — a deliberate format drift from the ISO-8601 string `created_at`; NULL unless status is `complete`.
- `created_at` is an ISO-8601 string (text).
- `tags`, `report_ids`, `webhook_ids` are jsonb arrays; `redirect_uri` ~60% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "chk_<uuid>" |
| applicant_id | text | no | -> applicants.id (not FK-enforced) |
| status | text | no | in_progress / complete / withdrawn / paused / reopened |
| result | text | no | clear / consider / NULL; legacy PASS/FAIL on old rows |
| tags | jsonb | no | vendor array of free-text tags |
| report_ids | jsonb | no | array of report ids in this check |
| redirect_uri | text | no | applicant redirect link (~60% null) |
| applicant_provides_data | boolean | no | applicant-supplied-data flag |
| created_at | text | no | ISO-8601 string |
| completed_at_epoch | bigint | no | epoch SECONDS at completion (format drift; null while running) |
| href | text | no | vendor self-link |
| webhook_ids | jsonb | no | array of webhook ids |

## Joins / lineage
- `applicant_id` -> raw_onfido.applicants.id.
- `id` <- raw_onfido.reports.check_id, facial_similarity_reports.check_id, watchlist_reports.check_id.
- `id` matched by raw_compliance.case_management.source_ref when `source='onfido'`.
