# raw_zendesk.tickets

**Source system:** Zendesk Support API v2
**Grain:** one row per support ticket
**Approx rows (demo scale):** ~40,000
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
The primary support fact: every customer support ticket, its status, channel,
queue and CSAT outcome. ~40% of tickets reference the specific transfer they are
about via `transfer_id`, linking support to core transfers.

## Known data-quality quirks
- `solved_at` is an ISO-Z **text** string (legacy naming), NULL until solved; `created_at`/`updated_at` are tz timestamps.
- `priority` ~30% NULL, `type` ~40% NULL (Zendesk leaves them unset).
- `requester_email` is a dirty denormalized PII snapshot (~6% NULL) — prefer joining via `requester_id` → users.
- `satisfaction` is legacy free-text: offered / good / bad / unoffered.
- `transfer_id` (~40% populated) is the core transfers UUID.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | ticket id (PK) |
| requester_id | bigint | no | → users.id (end-user) |
| assignee_id | bigint | no | → users.id (agent), nullable |
| subject | text | no | ticket subject |
| status | text | no | new / open / pending / hold / solved / closed |
| priority | text | no | low / normal / high / urgent, sparse |
| type | text | no | question / incident / problem / task, sparse |
| channel | text | no | email / chat / api / web / mobile |
| tags | jsonb | no | tag array |
| group_name | text | no | support queue |
| requester_email | text | **yes** | dirty denormalized email snapshot |
| transfer_id | text | no | core transfers UUID, sparse |
| satisfaction | text | no | offered / good / bad / unoffered (legacy) |
| is_public | boolean | no | public ticket flag |
| created_at | timestamptz | no | created |
| updated_at | timestamptz | no | updated |
| solved_at | text | no | ISO-Z string, null until solved |
| metadata | jsonb | no | vendor payload, sparse |

## Joins / lineage
- `requester_id` / `assignee_id` → `raw_zendesk.users.id`.
- `transfer_id` → core transfers transfer_id (det_uuid), when present.
