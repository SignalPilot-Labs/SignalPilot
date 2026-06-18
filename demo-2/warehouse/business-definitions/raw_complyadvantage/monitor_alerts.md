# raw_complyadvantage.monitor_alerts

**Source system:** ComplyAdvantage (AML)
**Grain:** one row per alert raised by a monitor (a change in match state)
**Approx rows (demo scale):** ~13k
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
An alert fires when a monitored search changes — a new match appears, risk level
changes, or a match is removed. Alerts feed the compliance investigation queue.

## Known data-quality quirks
- `created_at` is an ISO-8601 string but `resolved_at_epoch_ms` is epoch MILLISECONDS
  (format drift within the same table).
- `status` carries legacy UPPERCASE 'OPEN' on old rows.
- `resolved_at_epoch_ms` null while open; `assigned_to` ~30% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | alert id, PK |
| monitor_id | bigint | no | -> monitors.id |
| search_id | bigint | no | denormalised -> searches.id |
| alert_type | text | no | new_match / match_removed / risk_changed / data_updated |
| previous_risk_level | text | no | prior risk level |
| new_risk_level | text | no | new risk level |
| status | text | no | open / acknowledged / closed / escalated (legacy OPEN) |
| assigned_to | text | no | analyst (~30% null) |
| resolved_at_epoch_ms | bigint | no | epoch MILLISECONDS; null while open |
| payload | jsonb | no | full alert blob |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- Joins to `raw_complyadvantage.monitors` on `monitor_id`, `searches` on `search_id`.
