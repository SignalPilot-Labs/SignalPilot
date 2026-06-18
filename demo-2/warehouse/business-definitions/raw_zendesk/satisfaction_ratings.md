# raw_zendesk.satisfaction_ratings

**Source system:** Zendesk Support API v2 (CSAT)
**Grain:** one row per CSAT survey response
**Approx rows (demo scale):** ~9,000
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
Customer satisfaction survey responses on solved/closed tickets (good/bad).
The basis for support CSAT reporting per agent and per queue.

## Known data-quality quirks
- Only solved tickets that returned good/bad ratings appear (offered/unoffered are not surveyed rows).
- `comment` is free text and ~50% NULL.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | rating id (PK) |
| ticket_id | bigint | no | → tickets.id |
| assignee_id | bigint | no | → users.id (agent rated) |
| requester_id | bigint | no | → users.id (rater) |
| score | text | no | good / bad / offered / unoffered |
| comment | text | no | free-text feedback, sparse |
| created_at | timestamptz | no | created |
| updated_at | timestamptz | no | updated |

## Joins / lineage
- `ticket_id` → `raw_zendesk.tickets.id`; `assignee_id`/`requester_id` → `raw_zendesk.users.id`.
