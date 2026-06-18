# raw_zendesk.tickets

**Source system:** Zendesk
**Grain:** one row per support ticket
**Approx rows (demo scale):** ~40,000 (end-users × 2)
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
The primary Zendesk support fact: one row per customer support ticket (transfer issues, refunds, KYC rejections, login problems, fee disputes, etc.). Each row carries status, priority, type, channel, assigned team/agent, and optionally the transfer the ticket is about. Source of truth for support volume, resolution, and CSAT analysis. Holds denormalized requester PII.

## Known data-quality quirks
- `solved_at` is **ISO-8601 text with a `Z` suffix** (legacy naming/format), null until the ticket is solved — unlike `created_at`/`updated_at` which are real timestamptz. Cast before date math.
- `priority` is sparse (null ~30%) and `type` is sparse (null ~40%).
- `requester_email` is a **denormalized PII snapshot** that is dirty (via `dirty_email`) and null ~6% — it may not match the current `raw_zendesk.users.email` for the requester.
- `transfer_id` is a sparse UUID (present ~40% of tickets) identifying the transfer the ticket concerns.
- `satisfaction` is legacy free-text (offered / good / bad / unoffered); it is `unoffered` for unsolved tickets.
- `status` is funnel-weighted toward solved/closed; a solved date past the data epoch is reset to status `open` with null `solved_at`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | ticket id, primary key |
| requester_id | bigint | no | -> raw_zendesk.users.id (end-user) |
| assignee_id | bigint | no | -> raw_zendesk.users.id (agent); null when unassigned |
| subject | text | no | ticket subject line |
| status | text | no | new / open / pending / hold / solved / closed |
| priority | text | no | low / normal / high / urgent; sparse (~30% null) |
| type | text | no | question / incident / problem / task; sparse (~40% null) |
| channel | text | no | email / chat / api / web / mobile |
| tags | jsonb | no | array of tag strings (billing, transfer, kyc, ...) |
| group_name | text | no | support team queue (Tier 1, Payments Ops, Fraud, ...) |
| requester_email | text | yes | denormalized dirty email snapshot; null ~6% (PII) |
| transfer_id | text | no | UUID of the transfer the ticket is about; sparse (~40%) |
| satisfaction | text | no | offered / good / bad / unoffered (legacy free-text) |
| is_public | boolean | no | public-visibility flag |
| created_at | timestamptz | no | creation time (tz-aware) |
| updated_at | timestamptz | no | last update (tz-aware) |
| solved_at | text | no | ISO-Z string; null until solved (legacy naming) |
| metadata | jsonb | no | vendor blob, e.g. {"via": "email"}; nullable |

## Joins / lineage
- `requester_id` / `assignee_id` -> `raw_zendesk.users.id`.
- `requester_email` = dirty customer email (denormalized) — fuzzy customer join key.
- `transfer_id` = transfer UUID — links a ticket to the transfers fact.
- `id` <- `raw_zendesk.ticket_comments.ticket_id`, `raw_zendesk.satisfaction_ratings.ticket_id`.
