# raw_compliance.sanctions_list

**Source system:** internal NALA compliance operations (consolidated sanctions-list lookup the team maintains)
**Grain:** one row per sanctions-list entry (a listed entity)
**Approx rows (demo scale):** 400 (fixed-size reference lookup)
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
The consolidated sanctions list NALA's compliance team screens customers and counterparties against — entries drawn from OFAC SDN, UN Consolidated, UK HMT and EU Consolidated. Each row is a listed individual, entity, vessel or aircraft with its program code, aliases, nationality and listing date. This is a reference lookup, not customer data; PII here belongs to the listed (sanctioned) entity.

## Known data-quality quirks
- Fixed 400-entry synthetic reference set.
- ~70% individuals, the rest entity/vessel/aircraft.
- `dob` is only populated for individuals and is ~50% null even then; `nationality` (ISO-2) ~30% null.
- `is_active` true on ~92% of rows; `aliases` is a jsonb array (may be empty).
- Internal system: `created_at` is a clean tz-aware `timestamptz`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| entry_id | bigint | no | PK |
| list_name | text | no | OFAC SDN / UN Consolidated / UK HMT / EU Consolidated |
| entity_name | text | yes | sanctioned entity name (listed-entity PII) |
| entity_type | text | no | individual / entity / vessel / aircraft |
| aliases | jsonb | yes | array of aka names |
| program | text | no | sanctions program code |
| nationality | text | no | ISO-2 nationality (~30% null) |
| dob | date | yes | date of birth for individuals (sparse) |
| listed_on | date | no | listing date |
| is_active | boolean | no | active-listing flag (~92% true) |
| source_url | text | no | source list URL |
| created_at | timestamptz | no | row insert time |

## Joins / lineage
- Reference lookup — screened against by raw_complyadvantage.search_hits.sources and raw_onfido.watchlist_reports.sources_searched (list names), not via a hard key.
