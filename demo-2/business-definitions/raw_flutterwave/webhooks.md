# raw_flutterwave.webhooks

**Source system:** Flutterwave v3 API (webhook events to NALA's endpoint)
**Grain:** one row per webhook event received
**Approx rows (demo scale):** ~640k
**Loaded by:** warehouse/generators/gen_raw_flutterwave.py

## Business definition
Raw Flutterwave webhook deliveries (e.g. `transfer.completed`). The terminal
status of a payout arrives here. Source of truth for resolved transfer outcomes.

## Known data-quality quirks
- `received_at` is a naive ISO string with NO timezone (drift vs other sources' ISO-Z).
- ~3% are duplicate deliveries (`is_duplicate = true`) — dedupe on `transfer_id`.
- `verif_hash_valid` is false for ~3% (failed verif-hash header) — those should be treated with suspicion.
- Pending transfers have no terminal webhook row.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| webhook_id | bigint | no | PK (synthetic) |
| event | text | no | e.g. "transfer.completed" |
| event_type | text | no | "Transfer" / "Card" |
| transfer_id | bigint | no | ref `transfers.id` |
| reference | text | no | transfer reference |
| status | text | no | SUCCESSFUL / FAILED / legacy QUEUED |
| verif_hash_valid | boolean | no | did the verif-hash validate |
| received_at | text | no | naive ISO string (no tz) |
| is_duplicate | boolean | no | re-delivered event |
| payload | jsonb | no | full webhook body |

## Joins / lineage
- Joins to `raw_flutterwave.transfers` on `transfer_id`. Dedupe `is_duplicate = false`.
