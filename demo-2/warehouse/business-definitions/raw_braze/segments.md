# raw_braze.segments

**Source system:** Braze (audience segment definitions)
**Grain:** one row per segment
**Approx rows (demo scale):** ~750
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Audience definitions in Braze (e.g. "UK Senders", "Lapsed 30d") used to target
campaigns and canvases. `estimated_size` is the last computed member count and
is a snapshot, not a live join.

## Known data-quality quirks
- `estimated_size` is a stale snapshot; not exact and not backed by a member table here.
- `description` is ~40% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| segment_id | text | no | 24-hex api_id (PK) |
| name | text | no | segment name |
| description | text | no | free text, sparse |
| analytics_tracking_enabled | boolean | no | tracking flag |
| tags | jsonb | no | array of tags |
| estimated_size | bigint | no | last computed member count (snapshot) |
| created_at | timestamptz | no | tz-aware |
| updated_at | timestamptz | no | tz-aware |

## Joins / lineage
- Standalone reference; no enforced FK to other tables.
