# raw_zendesk.ticket_comments

**Source system:** Zendesk
**Grain:** one row per comment (public reply or private note) on a ticket
**Approx rows (demo scale):** ~120,000 (~40,000 tickets × 1-5 comments)
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
Individual comments on Zendesk tickets — both customer-facing public replies and internal agent notes. Each row records the author, the body text, whether it was public, and whether the author was an agent. Used for conversation reconstruction, first-response/handle-time analysis, and (in real life) PII-bearing free text.

## Known data-quality quirks
- `body` is free text and in real life may contain PII (names, emails, document references) — treat as PII-bearing and redact in audit/exports.
- Authorship alternates: odd-indexed comments are agent replies only when the ticket has an assignee, so a ticket with no assignee has user-only comments.
- `is_agent` mirrors the author role; `public` is always true in the generated data even though the schema allows private notes.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | comment id, primary key |
| ticket_id | bigint | no | -> raw_zendesk.tickets.id |
| author_id | bigint | no | -> raw_zendesk.users.id |
| body | text | yes | free-text comment body; may contain PII (PII) |
| public | boolean | no | public reply (true) vs internal note |
| is_agent | boolean | no | whether the author is an agent |
| created_at | timestamptz | no | comment time (tz-aware) |

## Joins / lineage
- `ticket_id` -> `raw_zendesk.tickets.id`.
- `author_id` -> `raw_zendesk.users.id`.
