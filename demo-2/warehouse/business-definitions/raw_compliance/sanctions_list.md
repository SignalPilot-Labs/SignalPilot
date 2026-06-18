# raw_compliance.sanctions_list

**Source system:** NALA internal compliance system (consolidated sanctions lookup)
**Grain:** one row per sanctioned entity entry (lookup table)
**Approx rows (demo scale):** ~400
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
The consolidated sanctions list the compliance team screens names against (OFAC SDN,
UN, UK HMT, EU). A reference/lookup table, not customer data.

## Known data-quality quirks
- nationality / dob sparse (only individuals, ~50% populated).
- aliases is a jsonb array.
- is_active ~92% true (some entries delisted).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| entry_id | bigint | no | PK |
| list_name | text | no | OFAC SDN / UN Consolidated / UK HMT / EU Consolidated |
| entity_name | text | yes | sanctioned entity name |
| entity_type | text | no | individual / entity / vessel / aircraft |
| aliases | jsonb | yes | aka name array |
| program | text | no | sanctions program code |
| nationality | text | no | ISO-2 (sparse) |
| dob | date | yes | dob for individuals (sparse) |
| listed_on | date | no | date listed |
| is_active | boolean | no | currently listed |
| source_url | text | no | source reference url |
| created_at | timestamptz | no | row creation |

## Joins / lineage
- Lookup: screened against by name/alias (fuzzy, no hard key).
