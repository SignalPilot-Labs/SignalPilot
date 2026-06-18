# raw_complyadvantage.searches

**Source system:** ComplyAdvantage (AML / sanctions / PEP screening)
**Grain:** one row per screening search (one per screened customer)
**Approx rows (demo scale):** ~57k (~95% of customers screened)
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
A ComplyAdvantage search screens a customer's name (+ filters) against global
sanctions, PEP and adverse-media watchlists at onboarding. The returned
match_status and risk_level drive whether NALA opens a compliance case.

## Known data-quality quirks
- `created_at`/`updated_at` are ISO-8601 strings (text), space-separated (no Z).
- `ref` and `client_ref` are duplicate columns (client_ref is the legacy name).
- `ref` ~6% null; `nala_customer_email` ~40% null (dirtied via dirty_email).
- `filters`, `tags` are vendor jsonb.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | ComplyAdvantage numeric search id, PK |
| ref | text | no | client reference = NALA customer code (join key) |
| nala_customer_email | text | yes | dirtied email used for the search (alt join key, sparse) |
| search_term | text | yes | the name string searched |
| client_ref | text | no | legacy duplicate of ref |
| searcher_id | text | no | service account that ran the search |
| assignee_id | text | no | analyst assigned (~70% null) |
| filters | jsonb | no | {types, birth_year, ...} |
| match_status | text | no | no_match / potential_match / false_positive / true_positive / unknown |
| risk_level | text | no | low / medium / high / unknown |
| total_hits | integer | no | number of hits returned |
| total_matches | integer | no | number of matches |
| share_url | text | no | public share link |
| is_monitored | boolean | no | whether an ongoing monitor exists |
| created_at | text | no | ISO-8601 string |
| updated_at | text | no | ISO-8601 string |
| tags | jsonb | no | tag array |

## Joins / lineage
- Joins to NALA core customers on `ref = customers.code` (~6% null).
- 1:N to `raw_complyadvantage.search_hits` on `id = search_id`.
- 1:1/1:N to `raw_complyadvantage.monitors` on `id = search_id`.
