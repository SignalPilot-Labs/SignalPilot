# raw_intercom.conversation_parts

**Source system:** Intercom API v2.11
**Grain:** one row per part (message/note/system event) within a conversation
**Approx rows (demo scale):** ~120,000
**Loaded by:** warehouse/generators/gen_raw_intercom.py

## Business definition
The individual entries inside an Intercom conversation: customer messages, admin
replies, internal notes and system events (assignment/close/open). Used to
reconstruct timelines and measure reply volume.

## Known data-quality quirks
- `created_at` / `notified_at` are **epoch seconds**; `notified_at` ~60% NULL.
- `body` is HTML/text and NULL for system parts (assignment/close/open).
- `author_type` = user / admin / bot.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric string id (PK) |
| conversation_id | text | no | → conversations.id |
| part_type | text | no | comment / note / assignment / close / open |
| body | text | **yes** | HTML/text body (may contain PII), nullable |
| author_type | text | no | user / admin / bot |
| author_id | text | no | author id |
| notified_at | bigint | no | epoch s, sparse |
| created_at | bigint | no | epoch s |

## Joins / lineage
- `conversation_id` → `raw_intercom.conversations.id`.
