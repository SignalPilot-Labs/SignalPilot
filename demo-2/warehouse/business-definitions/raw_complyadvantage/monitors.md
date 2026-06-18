# raw_complyadvantage.monitors

**Source system:** ComplyAdvantage (AML)
**Grain:** one row per ongoing monitor registration on a search
**Approx rows (demo scale):** ~18k
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
A monitor keeps a search under ongoing surveillance so changes to watchlists
re-screen the customer automatically. High/medium-risk customers are almost always
monitored.

## Known data-quality quirks
- `monitor_frequency` carries legacy UPPERCASE values (e.g. 'DAILY') on old rows.
- `last_run_at` ~10% null (never run).
- Timestamps are ISO-8601 strings.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | monitor id, PK |
| search_id | bigint | no | -> searches.id |
| ref | text | no | NALA customer code |
| is_active | boolean | no | monitor active flag |
| monitor_frequency | text | no | daily / weekly / monthly (legacy uppercase) |
| last_run_at | text | no | ISO string; ~10% null |
| created_at | text | no | ISO-8601 string |
| updated_at | text | no | ISO-8601 string |

## Joins / lineage
- Joins to `raw_complyadvantage.searches` on `search_id`.
- 1:N to `raw_complyadvantage.monitor_alerts` on `id = monitor_id`.
