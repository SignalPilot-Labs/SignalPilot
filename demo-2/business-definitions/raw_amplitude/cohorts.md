# raw_amplitude.cohorts

**Source system:** Amplitude
**Grain:** one row per Amplitude cohort definition
**Approx rows (demo scale):** ~8
**Loaded by:** warehouse/generators/gen_raw_amplitude.py

## Business definition
Behavioral cohort definitions authored in the Amplitude UI (e.g. "Activated Senders", "Churn Risk - KE", "High Value"). This is a small lookup/metadata table describing each cohort's intent, type, and approximate size; it documents the segmentation logic used by growth analysts.

## Known data-quality quirks
- Tiny fixed lookup (8 rows from a fixed definition list).
- `owner` is an analyst email and is ~20% null (PII-ish).
- `size` is the member count at definition time, not current — stale by design.
- `archived` is true for ~15% of cohorts.
- No per-member rows here; this is definition metadata only.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| cohort_id | text | no | Amplitude cohort id (PK) |
| name | text | no | Cohort name (Activated Senders, Churn Risk - KE, ...) |
| description | text | no | Human description of cohort logic |
| cohort_type | text | no | static / dynamic |
| size | integer | no | Member count at definition time (stale) |
| owner | text | yes | Analyst email (~20% null) |
| created_at | timestamptz | no | Cohort creation time |
| last_computed_at | timestamptz | no | Last recompute time |
| archived | boolean | no | Whether the cohort is archived |

## Joins / lineage
- Standalone metadata; no row-level join key to events or users (membership is not materialized here).
- Conceptually relates to `raw_amplitude.user_properties.cohort` (deprecated legacy label) by name.
