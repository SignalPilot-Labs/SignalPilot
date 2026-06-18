# raw_intercom.conversations

**Source system:** Intercom API v2.11
**Grain:** one row per Intercom conversation (chat thread)
**Approx rows (demo scale):** ~30,000
**Loaded by:** warehouse/generators/gen_raw_intercom.py

## Business definition
In-app conversational support threads. Complements Zendesk (Intercom handles
live/in-app chat). Contacts link to the canonical customer via
`contact_external_id` (customer code) and a dirty `contact_email`. CSAT lives in
`rating` (1..5); response/close timings live in the `statistics` JSON blob.

## Known data-quality quirks
- All timestamp columns are **UNIX epoch seconds** EXCEPT `waiting_since`, which is **epoch milliseconds** (Intercom inconsistency).
- `waiting_since` populated only when `state='open'`; `snoozed_until` only when snoozed.
- `contact_email` is dirty and ~7% NULL (PII).
- `rating` (1..5 CSAT) is sparse — only ~40% of closed conversations.
- `statistics` is a JSON blob (`first_response_time`, `time_to_close`, `count_reopens`).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric string id (PK) |
| contact_external_id | text | no | NALA customer code |
| contact_email | text | **yes** | dirty email, sparse |
| state | text | no | open / closed / snoozed |
| open | boolean | no | open flag |
| read | boolean | no | read flag |
| priority | text | no | priority / not_priority |
| source_type | text | no | conversation / email / push / chat |
| source_subject | text | no | initiating subject |
| assignee_admin_id | text | no | agent id, nullable |
| team_assignee_id | text | no | team id, nullable |
| waiting_since | bigint | no | epoch **ms**, nullable |
| snoozed_until | bigint | no | epoch s, nullable |
| sla_breached | boolean | no | SLA breach flag |
| rating | integer | no | CSAT 1..5, sparse |
| tags | jsonb | no | tag array |
| statistics | jsonb | no | timing metrics blob |
| created_at | bigint | no | epoch s |
| updated_at | bigint | no | epoch s |

## Joins / lineage
- `raw_intercom.conversation_parts.conversation_id` → `conversations.id`.
- `contact_external_id` → NALA customer code (cross-source with braze/zendesk).
