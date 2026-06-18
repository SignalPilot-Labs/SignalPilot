# raw_zendesk.ticket_comments

**Source system:** Zendesk Support API v2
**Grain:** one row per comment/reply on a ticket
**Approx rows (demo scale):** ~120,000
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
The back-and-forth on each ticket: public replies and (potentially) private agent
notes. Used to measure response volume and reconstruct conversation timelines.

## Known data-quality quirks
- `body` is free text and in real life may contain PII inline (treat as sensitive).
- `is_agent` distinguishes staff replies from customer replies.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | comment id (PK) |
| ticket_id | bigint | no | → tickets.id |
| author_id | bigint | no | → users.id |
| body | text | **yes** | free text (may contain PII) |
| public | boolean | no | public vs private |
| is_agent | boolean | no | agent-authored flag |
| created_at | timestamptz | no | created |

## Joins / lineage
- `ticket_id` → `raw_zendesk.tickets.id`; `author_id` → `raw_zendesk.users.id`.
