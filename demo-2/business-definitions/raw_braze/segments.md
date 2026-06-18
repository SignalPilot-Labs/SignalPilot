# raw_braze.segments

**Source system:** Braze
**Grain:** one row per Braze audience segment definition
**Approx rows (demo scale):** ~750 (customers / 80)
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Audience segment definitions used to target Braze campaigns and canvases (e.g. "UK Senders", "Lapsed 30d", "High Value", "Kenya Corridor", "KYC Incomplete"). Each row holds the segment's name, description, and last-computed estimated member count. Used for audience sizing and CRM targeting analysis.

## Known data-quality quirks
- `estimated_size` is a last-computed snapshot, not live — it can be stale relative to the actual current audience.
- `description` is null ~40% of the time.
- `analytics_tracking_enabled` is true ~70% of the time; segments with it disabled won't have full event tracking.
- Names repeat with a ` v2`, ` v3` suffix once the base name list is exhausted (versioned duplicates of the same logical segment).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| segment_id | text | no | 24-hex Braze api_id, primary key |
| name | text | no | segment name, e.g. "UK Senders" |
| description | text | no | free-text description; nullable (~40%) |
| analytics_tracking_enabled | boolean | no | whether analytics tracking is on (~70% true) |
| tags | jsonb | no | array of tag strings (growth, crm, lifecycle) |
| estimated_size | bigint | no | last-computed member count (snapshot, may be stale) |
| created_at | timestamptz | no | creation time (tz-aware) |
| updated_at | timestamptz | no | last update (tz-aware) |

## Joins / lineage
- No direct foreign keys in this raw layer; segments are referenced by campaign/canvas configuration not modeled here.
- No customer linkage at this grain.
