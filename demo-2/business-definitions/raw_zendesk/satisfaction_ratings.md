# raw_zendesk.satisfaction_ratings

**Source system:** Zendesk
**Grain:** one row per CSAT survey response on a solved ticket
**Approx rows (demo scale):** ~12,000 (subset of solved tickets rated good/bad)
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
Customer satisfaction (CSAT) survey responses captured on solved Zendesk tickets. Each row records the score and optional free-text feedback. Used for support quality and agent CSAT reporting. Only tickets whose `satisfaction` resolved to `good` or `bad` produce a rating row.

## Known data-quality quirks
- Rows exist only for tickets with a `good` or `bad` satisfaction outcome — `offered`/`unoffered` tickets have no rating row (this table is sparse relative to tickets).
- `comment` is free-text feedback, sparse (null ~50%), and PII-bearing in real life.
- `created_at` and `updated_at` are both set to the parent ticket's `updated_at` (they are not independent rating timestamps).
- `score` reuses the legacy free-text vocabulary (good / bad / offered / unoffered) rather than a numeric scale.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | rating id, primary key |
| ticket_id | bigint | no | -> raw_zendesk.tickets.id |
| assignee_id | bigint | no | -> raw_zendesk.users.id (agent) |
| requester_id | bigint | no | -> raw_zendesk.users.id (end-user) |
| score | text | no | good / bad / offered / unoffered (legacy free-text) |
| comment | text | yes | free-text feedback; sparse (~50% null); may contain PII |
| created_at | timestamptz | no | copied from ticket updated_at |
| updated_at | timestamptz | no | copied from ticket updated_at |

## Joins / lineage
- `ticket_id` -> `raw_zendesk.tickets.id`.
- `assignee_id` / `requester_id` -> `raw_zendesk.users.id`.
