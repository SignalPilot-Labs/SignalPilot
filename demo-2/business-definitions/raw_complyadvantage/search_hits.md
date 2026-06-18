# raw_complyadvantage.search_hits

**Source system:** ComplyAdvantage (AML / sanctions / PEP screening)
**Grain:** one row per hit (a matched watchlist entity) inside a search
**Approx rows (demo scale):** ~7,000 (most searches are clean; only the ~10% matched tail emits hits)
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
A single matched watchlist entity returned by a ComplyAdvantage search — the person/organisation/vessel the searched name hit against, with the lists it appears on (`sources`), the match types, the vendor `match_score`, and the per-hit disposition. The compliance team works each hit to confirm or whitelist the match. Carries PII of the matched entity, not the NALA customer directly.

## Known data-quality quirks
- Sparse table: ~90% of searches return zero hits, so this is the matched tail only.
- `match_score` (0..100) is ~15% null for legacy rows.
- `entity_name` uses a "LAST, First" matched-entity style.
- `match_types`, `aka`, `sources`, `types`, `fields` are all jsonb (the `fields` blob holds matched dob/nationality).
- `created_at` is an ISO-8601 string (text).
- `id` is a surrogate bigserial (the vendor nests hits under a search).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigserial | no | PK, surrogate hit id |
| search_id | bigint | no | -> searches.id |
| doc_id | text | no | vendor entity document id |
| entity_name | text | yes | matched person/org name (matched-entity PII) |
| entity_type | text | no | person / organisation / vessel / aircraft |
| match_types | jsonb | no | ["name_exact","aka_fuzzy",...] |
| aka | jsonb | yes | also-known-as names blob |
| sources | jsonb | no | watchlist sources (OFAC SDN, UN Consolidated, ...) |
| types | jsonb | no | ["sanction","pep-class-1","adverse-media-...",...] |
| match_score | numeric(5,2) | no | vendor score 0..100 (~15% null) |
| is_whitelisted | boolean | no | analyst-whitelisted flag |
| match_status | text | no | per-hit disposition: potential_match / false_positive / true_positive |
| fields | jsonb | yes | raw matched fields (dob, nationality, associates) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `search_id` -> raw_complyadvantage.searches.id.
