# raw_braze.canvases

**Source system:** Braze
**Grain:** one row per multi-step Braze Canvas (orchestration journey)
**Approx rows (demo scale):** ~1,000 (customers / 60)
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Braze "Canvas" multi-step orchestration journeys — automated, branching message flows such as onboarding, winback, and lifecycle sequences. Each row captures a journey's step count, status, and entry window. Used to attribute `raw_braze.messages_sent` events emitted from a journey (rather than a single campaign).

## Known data-quality quirks
- `first_entry` and `last_entry` are ISO-8601 text with a `Z` suffix (not timestamps); cast before date math.
- `first_entry` is null ~10% of the time; `last_entry` is null whenever `first_entry` is null.
- `is_archived` (~15% true) is independent of `status` here, unlike campaigns.
- `enabled` and `is_archived` can both vary — a canvas may be archived but still flagged enabled.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| canvas_id | text | no | 24-hex Braze api_id, primary key |
| name | text | no | journey name, e.g. "Reactivation Journey" |
| tags | jsonb | no | array of tag strings (onboarding, winback, ...) |
| num_steps | integer | no | number of steps in the journey (2-8) |
| status | text | no | active / draft / archived |
| is_archived | boolean | no | archive flag (~15% true), independent of status |
| enabled | boolean | no | whether the journey is enabled (~90% true) |
| first_entry | text | no | ISO-Z string, first entry time; nullable |
| last_entry | text | no | ISO-Z string, last entry time; null when first_entry null |
| created_at | timestamptz | no | creation time (tz-aware) |
| updated_at | timestamptz | no | last update (tz-aware) |

## Joins / lineage
- `canvas_id` = `raw_braze.messages_sent.canvas_id` (journey-sourced sends, ~35% of sends).
- No customer linkage at this grain.
