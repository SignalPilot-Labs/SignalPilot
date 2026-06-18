# raw_onfido.checks

**Source system:** Onfido (KYC)
**Grain:** one row per check (a check groups one or more reports)
**Approx rows (demo scale):** ~70k (one per customer + ~18% reverification)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
An Onfido "check" is a single verification run against an applicant. It bundles the
individual reports (document, facial similarity, watchlist) and carries the overall
result NALA acts on at onboarding and re-verification.

## Known data-quality quirks
- `created_at` is an ISO-8601 string; `completed_at_epoch` is epoch SECONDS (bigint)
  — completion time is stored in a different format from creation (vendor drift).
- `result` is null while a check is `in_progress`/`withdrawn`.
- Oldest rows (<=2020) carry legacy `result` values `PASS`/`FAIL` instead of
  `clear`/`consider`.
- `report_ids`, `tags`, `webhook_ids` are vendor jsonb arrays.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | check id ("chk_<uuid>"), PK |
| applicant_id | text | no | -> applicants.id |
| status | text | no | in_progress / complete / withdrawn / paused / reopened |
| result | text | no | clear / consider / NULL; legacy PASS/FAIL |
| tags | jsonb | no | free-text tag array |
| report_ids | jsonb | no | ids of reports in this check |
| redirect_uri | text | no | hosted-flow redirect (~60% null) |
| applicant_provides_data | boolean | no | applicant-supplied-data flag |
| created_at | text | no | ISO-8601 string |
| completed_at_epoch | bigint | no | epoch SECONDS; null while running |
| href | text | no | vendor self-link |
| webhook_ids | jsonb | no | webhook ids notified |

## Joins / lineage
- Joins to `raw_onfido.applicants` on `applicant_id`.
- 1:N to `raw_onfido.reports` / `facial_similarity_reports` / `watchlist_reports`
  on `check_id`.
