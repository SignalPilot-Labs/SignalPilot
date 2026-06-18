# raw_complyadvantage.monitor_alerts

**Source system:** ComplyAdvantage (AML / sanctions / PEP screening)
**Grain:** one row per alert raised by a monitor (a change in match state over time)
**Approx rows (demo scale):** ~15,000 (monitors of matched customers raise 1-3 alerts; a small random tail otherwise)
**Loaded by:** warehouse/generators/gen_raw_complyadvantage.py

## Business definition
An alert raised by an ongoing ComplyAdvantage monitor when the screened customer's match state changes — a new match appears, a match is removed, risk changes, or entity data updates. The compliance team works each alert through an open -> acknowledged/closed/escalated lifecycle; `previous_risk_level`/`new_risk_level` capture the risk delta that triggered it.

## Known data-quality quirks
- `status` carries a legacy uppercase `OPEN` on ~40% of pre-2021 open rows; modern rows are lowercase open/acknowledged/closed/escalated.
- `resolved_at_epoch_ms` is stored as epoch MILLISECONDS (bigint) — a deliberate format drift from the ISO-8601 string `created_at`; NULL while the alert is open.
- `assigned_to` ~30% null.
- `payload` is a full-alert jsonb blob; `created_at` is an ISO-8601 string.
- Most alerts cluster on monitors whose underlying search had hits.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK, alert id |
| monitor_id | bigint | no | -> monitors.id |
| search_id | bigint | no | denormalised -> searches.id |
| alert_type | text | no | new_match / match_removed / risk_changed / data_updated |
| previous_risk_level | text | no | risk level before the change |
| new_risk_level | text | no | risk level after the change |
| status | text | no | open / acknowledged / closed / escalated; legacy OPEN |
| assigned_to | text | no | analyst id (~30% null) |
| resolved_at_epoch_ms | bigint | no | epoch MILLISECONDS at resolution (format drift; null while open) |
| payload | jsonb | no | full alert blob |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `monitor_id` -> raw_complyadvantage.monitors.id.
- `search_id` -> raw_complyadvantage.searches.id.
