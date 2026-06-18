# raw_braze.canvases

**Source system:** Braze (Canvas = multi-step orchestration journeys)
**Grain:** one row per Canvas (journey)
**Approx rows (demo scale):** ~1,000
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Multi-step lifecycle journeys (e.g. onboarding, win-back) orchestrated in Braze.
A Canvas can send many messages across steps; `messages_sent` rows reference it
via `canvas_id` when the send originated from a Canvas rather than a campaign.

## Known data-quality quirks
- `first_entry` / `last_entry` are ISO-Z **text** strings; null on unused journeys.
- A send row in `messages_sent` has exactly one of `campaign_id` / `canvas_id` populated.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| canvas_id | text | no | 24-hex Braze api_id (PK) |
| name | text | no | journey name |
| tags | jsonb | no | array of tag strings |
| num_steps | integer | no | number of steps in the journey |
| status | text | no | active / draft / archived |
| is_archived | boolean | no | archived flag |
| enabled | boolean | no | currently enabled |
| first_entry | text | no | ISO-Z string, nullable |
| last_entry | text | no | ISO-Z string, nullable |
| created_at | timestamptz | no | tz-aware |
| updated_at | timestamptz | no | tz-aware |

## Joins / lineage
- `raw_braze.messages_sent.canvas_id` → `canvases.canvas_id`.
