# raw_intercom.conversation_parts

**Source system:** Intercom
**Grain:** one row per part (message, note, or system action) within a conversation
**Approx rows (demo scale):** ~105,000 (~30,000 conversations × 1-6 parts)
**Loaded by:** warehouse/generators/gen_raw_intercom.py

## Business definition
Individual parts within an Intercom conversation — customer/admin messages, internal notes, and system actions (assignment, close, open). Each row records the part type, body, author type/id, and timestamps. Used to reconstruct conversation threads and compute response/handling metrics.

## Known data-quality quirks
- Timestamps are **UNIX epoch SECONDS** (`created_at`, `notified_at`); consistent within Intercom but drift against Zendesk ISO-Z strings.
- `notified_at` is sparse — null ~60% of the time.
- `body` is HTML/text and is null for system parts (`assignment`, `close`, `open`); only `comment` and `note` parts carry a body. Free-text bodies are PII-bearing in real life.
- `author_id` is a synthetic id: `admin_<n>` for admins/bots, `user_<conversation_id>` for users — it is NOT a NALA customer code and not a Zendesk user id.
- `author_type` `bot` is allowed by the schema; the generator emits user / admin.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric-string part id, primary key |
| conversation_id | text | no | -> raw_intercom.conversations.id |
| part_type | text | no | comment / note / assignment / close / open |
| body | text | yes | HTML/text body; null for system parts; PII-bearing free text |
| author_type | text | no | user / admin / bot |
| author_id | text | no | 'admin_<n>' or 'user_<conversation_id>' (not a NALA/Zendesk id) |
| notified_at | bigint | no | epoch SECONDS; sparse (~60% null) |
| created_at | bigint | no | epoch SECONDS |

## Joins / lineage
- `conversation_id` -> `raw_intercom.conversations.id`.
- No direct NALA customer key on parts; resolve the customer via the parent conversation's `contact_external_id` / `contact_email`.
