# raw_flutterwave.transfer_retries

**Source system:** Flutterwave v3 API (transfer retry events)
**Grain:** one row per retry attempt of a failed/pending transfer
**Approx rows (demo scale):** ~170k
**Loaded by:** warehouse/generators/gen_raw_flutterwave.py

## Business definition
When a Flutterwave payout fails or hangs, NALA retries it. Each retry attempt is
logged here (multiple rows per transfer). Used to measure payout reliability and
eventual success after retry.

## Known data-quality quirks
- Only failed/pending transfers (~14%) have retry rows; successful first-attempts have none.
- `attempt_number` increments 1..N per transfer; the final attempt may be SUCCESSFUL or stay FAILED/PENDING.
- `retried_at` is `yyyy-MM-dd HH:mm:ss` string.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK |
| transfer_id | bigint | no | ref `transfers.id` (soft) |
| attempt_number | integer | no | 1-based attempt counter |
| status | text | no | SUCCESSFUL / FAILED / PENDING |
| reference | text | no | retry idempotency reference |
| response_code / response_message | text | no | provider response |
| retried_at | timestamptz | no | retry time |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- Joins to `raw_flutterwave.transfers` on `transfer_id` (soft, same schema).
