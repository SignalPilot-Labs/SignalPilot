# raw_zendesk.users

**Source system:** Zendesk Support API v2
**Grain:** one row per Zendesk user (end-user or agent)
**Approx rows (demo scale):** ~20,000
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
People in Zendesk: support agents/admins (NALA staff) and end-users (NALA
customers who contacted support). End-users link to the canonical customer via
`external_id` (customer code) and a dirty `email`.

## Known data-quality quirks
- PII: `name`, `email`, `phone`. `email` is dirty (casing/space/typo drift) and ~6% NULL; `phone` ~50% NULL.
- `external_id` is the NALA customer code `CUS_XXXXXXXX` for end-users; NULL for agents.
- `role` = end-user / agent / admin. Agent emails are `@nala.com`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | Zendesk user id (PK) |
| name | text | **yes** | full name |
| email | text | **yes** | email, dirty, sparse |
| phone | text | **yes** | E.164, dirty, sparse |
| role | text | no | end-user / agent / admin |
| external_id | text | no | NALA customer code (end-users) |
| organization_id | bigint | no | nullable |
| locale | text | no | en-GB / en-US / fr / sw |
| time_zone | text | no | tz name |
| verified | boolean | no | email verified |
| suspended | boolean | no | suspended flag |
| tags | jsonb | no | tag array |
| created_at | timestamptz | no | created |
| updated_at | timestamptz | no | updated |

## Joins / lineage
- `raw_zendesk.tickets.requester_id` / `assignee_id` → `users.id`.
- `external_id` → NALA customer code (also raw_braze.messages_sent.external_user_id). `email` needs cleaning to join cross-source.
