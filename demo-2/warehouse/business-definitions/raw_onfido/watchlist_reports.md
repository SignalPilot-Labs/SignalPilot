# raw_onfido.watchlist_reports

**Source system:** Onfido (KYC)
**Grain:** one row per watchlist (PEP/sanctions/adverse-media) screening report
**Approx rows (demo scale):** ~50k (~70% of checks include a watchlist report)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
Onfido's in-flow watchlist screening: checks the applicant against PEP, sanctions
and adverse-media lists. Complements the dedicated ComplyAdvantage screening; both
feed compliance case management.

## Known data-quality quirks
- `n_matches` is 0 for ~93% of reports (most customers are clean).
- `records`/`sources_searched` are vendor jsonb arrays.
- `completed_at` null while the parent check runs.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | report id ("rep_<uuid>"), PK |
| check_id | text | no | -> checks.id |
| applicant_id | text | no | -> applicants.id |
| variant | text | no | standard / enhanced / peps_only / sanctions_only |
| result | text | no | clear / consider |
| n_matches | integer | no | number of watchlist records matched |
| records | jsonb | yes | match record blobs (names, sources, match_types) |
| sources_searched | jsonb | no | lists searched |
| shared_with_third_parties | boolean | no | data-sharing flag |
| created_at | text | no | ISO-8601 string |
| completed_at | text | no | ISO string; null while running |

## Joins / lineage
- Joins to `raw_onfido.checks` on `check_id`, `raw_onfido.applicants` on `applicant_id`.
