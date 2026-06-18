# raw_zendesk.users

**Source system:** Zendesk
**Grain:** one row per Zendesk user (end-user, agent, or admin)
**Approx rows (demo scale):** ~20,025 (~20,000 end-users + 25 agents)
**Loaded by:** warehouse/generators/gen_raw_zendesk.py

## Business definition
Zendesk Support user directory holding both NALA support agents and end-users (customers who have contacted support). End-users map to the NALA customer master; agents are internal staff. Used to resolve ticket requesters/assignees to people and to NALA customers. Contains PII (name, email, phone).

## Known data-quality quirks
- `email` is PII and dirty (case/whitespace/typo noise via `dirty_email`); null ~6% of end-user rows.
- `phone` is PII, dirty E.164, and sparse — null ~50% of the time.
- `external_id` is the NALA customer code only for `role = 'end-user'`; it is null for agents/admins.
- Agent emails follow a synthetic `firstname.supportN@nala.com` pattern; agents have no `external_id`.
- The first 25 rows (ids 500000-500024) are agents; end-users start at id 500025.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | Zendesk user id, primary key |
| name | text | yes | full name (PII) |
| email | text | yes | email, dirty; null ~6% of end-users (PII) |
| phone | text | yes | E.164 phone, dirty, sparse (~50% null) (PII) |
| role | text | no | end-user / agent / admin |
| external_id | text | no | NALA customer code 'CUS_...' for end-users; null for agents |
| organization_id | bigint | no | org id; nullable |
| locale | text | no | en-GB / en-US / fr / sw |
| time_zone | text | no | user time zone |
| verified | boolean | no | identity-verified flag |
| suspended | boolean | no | suspension flag (defaults false) |
| tags | jsonb | no | array of tag strings |
| created_at | timestamptz | no | creation time |
| updated_at | timestamptz | no | last update |

## Joins / lineage
- `external_id` = NALA customer code (`CUS_...`) for end-users — canonical customer join key.
- `email` = dirty customer email — fuzzy secondary join key into the customer master.
- `id` <- `raw_zendesk.tickets.requester_id` / `.assignee_id`, `raw_zendesk.ticket_comments.author_id`, `raw_zendesk.satisfaction_ratings.assignee_id` / `.requester_id`.
