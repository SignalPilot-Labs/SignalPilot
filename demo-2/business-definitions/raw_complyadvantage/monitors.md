# raw_complyadvantage.monitors

**Source system:** ComplyAdvantage (AML / sanctions / PEP screening)
**Grain:** one row per ongoing monitor registration on a search
**Approx rows (demo scale):** ~18,000 (high/medium-risk searches are almost always monitored, plus ~25% of the rest)
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
An ongoing-monitoring registration on a ComplyAdvantage search — keeps a screened customer under continuous surveillance so that changes to the watchlists (new matches, removals, risk changes) raise alerts over time. `monitor_frequency` and `is_active` govern the cadence; `last_run_at` records when monitoring last executed.

## Known data-quality quirks
- `monitor_frequency` carries legacy uppercase values (e.g. `DAILY`) on ~30% of pre-2021 rows; modern rows are lowercase daily/weekly/monthly.
- `last_run_at` is ~10% null (never run yet).
- `is_active` true on ~90% of rows.
- `created_at`/`updated_at`/`last_run_at` are ISO-8601 strings (text).
- `ref` mirrors the parent search's customer code.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK, monitor id |
| search_id | bigint | no | -> searches.id |
| ref | text | no | NALA customer code |
| is_active | boolean | no | monitor active flag (~90% true) |
| monitor_frequency | text | no | daily / weekly / monthly; legacy uppercase DAILY |
| last_run_at | text | no | ISO string; ~10% null (never run) |
| created_at | text | no | ISO-8601 string |
| updated_at | text | no | ISO-8601 string |

## Joins / lineage
- `search_id` -> raw_complyadvantage.searches.id.
- `ref` = NALA customer code -> customer_master.
- `id` <- raw_complyadvantage.monitor_alerts.monitor_id.
