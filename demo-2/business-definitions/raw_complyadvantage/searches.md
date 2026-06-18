# raw_complyadvantage.searches

**Source system:** ComplyAdvantage (AML / sanctions / PEP screening)
**Grain:** one row per screening search (each search screens one NALA customer)
**Approx rows (demo scale):** ~57,000 (~95% of customers are screened)
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
A ComplyAdvantage screening search — a name (and birth-year/country filter) run against sanctions, PEP and adverse-media watchlists for one NALA customer at onboarding. The `match_status`/`risk_level` and `total_hits`/`total_matches` summarise the screening outcome the compliance team triages; `is_monitored` indicates the search was placed under ongoing monitoring.

## Known data-quality quirks
- `ref` (= customer code, the primary join key) is ~6% null; `client_ref` is a legacy duplicate of `ref`.
- `nala_customer_email` is dirtied and sparse (~40% null) — a weak alternate join key.
- ~5% of customers are pre-vendor legacy and have no search row at all.
- Outcomes skew clean: ~90% `no_match`/low risk, ~7.5% false_positive/medium, the rest potential/true_positive at high/medium risk.
- `created_at`/`updated_at` are ISO-8601 strings (text).
- `assignee_id` ~70% null; `filters`/`tags` are jsonb.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK, ComplyAdvantage numeric search id |
| ref | text | no | client reference = NALA customer code (~6% null) |
| nala_customer_email | text | yes | dirtied email used to fire the search (~40% null) |
| search_term | text | yes | the name string searched |
| client_ref | text | no | legacy duplicate of ref |
| searcher_id | text | no | analyst / service-account id |
| assignee_id | text | no | assigned analyst id (~70% null) |
| filters | jsonb | no | {types, birth_year, countries, remove_deceased} |
| match_status | text | no | no_match / potential_match / false_positive / true_positive / unknown |
| risk_level | text | no | low / medium / high / unknown |
| total_hits | integer | no | number of hits returned |
| total_matches | integer | no | number of matches |
| share_url | text | no | vendor share link with token |
| is_monitored | boolean | no | placed under ongoing monitoring |
| created_at | text | no | ISO-8601 string |
| updated_at | text | no | ISO-8601 string |
| tags | jsonb | no | vendor tag array |

## Joins / lineage
- `ref` / `client_ref` = NALA customer code -> customer_master.
- `id` <- raw_complyadvantage.search_hits.search_id, monitors.search_id, monitor_alerts.search_id.
- `id` matched by raw_compliance.case_management.source_ref when `source='complyadvantage'`.
