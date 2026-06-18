# raw_complyadvantage.search_hits

**Source system:** ComplyAdvantage (AML)
**Grain:** one row per hit (a matched watchlist entity) within a search
**Approx rows (demo scale):** ~14k (sparse — most searches are clean)
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
Each row is a single watchlist entity that matched a search. Hits carry the match
types, sources (OFAC, UN, HMT...) and a vendor match score that analysts triage
into true/false positives.

## Known data-quality quirks
- Surrogate `id` (vendor nests hits under the search; we flatten).
- `match_score` ~15% null on legacy rows.
- `match_types`, `aka`, `sources`, `types`, `fields` are vendor jsonb.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigserial | no | surrogate PK |
| search_id | bigint | no | -> searches.id |
| doc_id | text | no | vendor entity document id |
| entity_name | text | yes | matched person/org name |
| entity_type | text | no | person / organisation / vessel / aircraft |
| match_types | jsonb | no | ["name_exact","aka_fuzzy",...] |
| aka | jsonb | yes | also-known-as names |
| sources | jsonb | no | watchlist source names |
| types | jsonb | no | ["sanction","pep-class-1",...] |
| match_score | numeric(5,2) | no | 0..100 vendor score (~15% null) |
| is_whitelisted | boolean | no | analyst-whitelisted match |
| match_status | text | no | per-hit disposition |
| fields | jsonb | yes | raw matched fields (dob, nationality) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- Joins to `raw_complyadvantage.searches` on `search_id`.
