# raw_intercom.conversations

**Source system:** Intercom
**Grain:** one row per Intercom conversation (chat thread)
**Approx rows (demo scale):** ~30,000 (customers / 2)
**Loaded by:** warehouse/generators/gen_raw_intercom.py

## Business definition
Intercom in-app conversational support threads between NALA customers and support admins/bots (transfer questions, FX help, refunds, KYC help, recipient issues). Each row captures the conversation state, assignment, SLA, rating, and an embedded statistics blob. The fact table for in-app support volume, response time, and SLA analysis. Holds dirty contact email PII.

## Known data-quality quirks
- Timestamps are **UNIX epoch SECONDS** (`created_at`, `updated_at`, `snoozed_until`), EXCEPT `waiting_since` which is **epoch MILLISECONDS** — divide `waiting_since` by 1000 before comparing. This drifts against Zendesk ISO-Z strings.
- `contact_email` is PII and dirty (via `dirty_email`); null ~7% of the time.
- `waiting_since` is populated only for `open` conversations; `snoozed_until` only for `snoozed` ones — both null otherwise.
- `rating` (1-5) is sparse — present only on ~40% of closed conversations; null elsewhere.
- `statistics` is a JSON blob (`first_response_time`, `time_to_close`, `count_reopens`, ...) where `time_to_close` is null for non-closed conversations.
- `open` is the boolean inverse of `state = 'closed'`; reconcile with `state` rather than trusting either alone.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | numeric-string conversation id, primary key |
| contact_external_id | text | no | NALA customer code 'CUS_...' |
| contact_email | text | yes | contact email, dirty; null ~7% (PII) |
| state | text | no | open / closed / snoozed |
| open | boolean | no | inverse of state = closed |
| read | boolean | no | read flag |
| priority | text | no | priority / not_priority |
| source_type | text | no | conversation / email / push / chat |
| source_subject | text | no | originating subject line |
| assignee_admin_id | text | no | agent admin id, e.g. 'admin_7'; nullable |
| team_assignee_id | text | no | team id; nullable |
| waiting_since | bigint | no | epoch MILLISECONDS; set only when state = open |
| snoozed_until | bigint | no | epoch SECONDS; set only when state = snoozed |
| sla_breached | boolean | no | SLA breach flag (~10% true) |
| rating | integer | no | conversation rating 1-5; sparse (~40% of closed) |
| tags | jsonb | no | array of tag strings (billing, transfer, kyc, bug) |
| statistics | jsonb | no | blob: first_response_time, time_to_close, count_reopens |
| created_at | bigint | no | epoch SECONDS |
| updated_at | bigint | no | epoch SECONDS |

## Joins / lineage
- `contact_external_id` = NALA customer code (`CUS_...`), canonical customer join key.
- `contact_email` = dirty customer email — fuzzy secondary join key.
- `id` <- `raw_intercom.conversation_parts.conversation_id`.
