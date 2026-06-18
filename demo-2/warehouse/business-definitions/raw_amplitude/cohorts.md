# raw_amplitude.cohorts

**Source system:** Amplitude (Behavioral Cohorts, defined in the UI)
**Grain:** one row per cohort definition
**Approx rows (demo scale):** 8
**Loaded by:** warehouse/generators/gen_raw_amplitude.py

## Business definition
Analyst-defined behavioral cohorts used for targeting and reporting (e.g. 'Activated Senders', 'Churn Risk - KE', 'High Value', 'KYC Stuck'). A lookup of cohort metadata; membership itself is computed in Amplitude.

## Known data-quality quirks
- `owner` (analyst email) ~20% null.
- ~15% archived; filter `archived = false` for live cohorts.
- `size` is the member count at definition time, not current.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| cohort_id | text | no | Amplitude cohort id. PK. |
| name | text | no | Cohort name. |
| description | text | no | Definition description. |
| cohort_type | text | no | static / dynamic. |
| size | integer | no | Member count at definition time. |
| owner | text | maybe | Analyst email; ~20% null. |
| created_at | timestamptz | no | When defined. |
| last_computed_at | timestamptz | no | Last membership recompute. |
| archived | boolean | no | Cohort retired. |

## Joins / lineage
- Standalone lookup; no enforced FK. No staging model.
