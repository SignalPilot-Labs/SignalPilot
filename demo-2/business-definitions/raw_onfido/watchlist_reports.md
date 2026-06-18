# raw_onfido.watchlist_reports

**Source system:** Onfido (identity-verification / KYC vendor)
**Grain:** one row per watchlist (PEP / sanctions / adverse-media) screening report run inside Onfido
**Approx rows (demo scale):** ~50,000 (~70% of checks include a watchlist report)
**Loaded by:** warehouse/generators/gen_raw_onfido.py

## Business definition
The Onfido watchlist report — screens the applicant against PEP, sanctions and adverse-media lists at onboarding. `n_matches` and the `records` blob capture any matched watchlist entities; `result` tells NALA whether the applicant is clear or needs compliance review. This is Onfido's in-line screening, complementary to the dedicated ComplyAdvantage searches.

## Known data-quality quirks
- Only ~70% of checks have a watchlist report (it is conditionally requested).
- Matches are rare: ~93% have `n_matches=0` (`result='clear'`); the tail has 1-4 matches and `result='consider'`.
- `records` is a jsonb array of match blobs containing the matched name (PII), match_types and source lists.
- `created_at` is an ISO string; `completed_at` is ISO and NULL while running.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "rep_<uuid>" |
| check_id | text | no | -> checks.id |
| applicant_id | text | no | -> applicants.id |
| variant | text | no | standard / enhanced / peps_only / sanctions_only |
| result | text | no | clear / consider |
| n_matches | integer | no | number of records matched (0 for ~93%) |
| records | jsonb | yes | array of match blobs (matched name, match_types, sources) |
| sources_searched | jsonb | no | array of list names searched |
| shared_with_third_parties | boolean | no | third-party-sharing flag |
| created_at | text | no | ISO-8601 string |
| completed_at | text | no | ISO string; null while running |

## Joins / lineage
- `check_id` -> raw_onfido.checks.id.
- `applicant_id` -> raw_onfido.applicants.id.
