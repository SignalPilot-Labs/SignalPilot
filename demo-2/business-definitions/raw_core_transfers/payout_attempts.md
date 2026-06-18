# raw_core_transfers.payout_attempts

**Source system:** internal core product DB (Postgres)
**Grain:** one row per payout attempt against a transfer (a transfer may retry)
**Approx rows (demo scale):** ~3,300,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The record of each attempt to deliver funds to the recipient via a payout partner/rail. Successful transfers have one attempt; failed/cancelled transfers may have multiple retries (up to 3) with partner response codes and messages.

## Known data-quality quirks
- COMPLETED/PENDING/REFUNDED transfers always have exactly one attempt; others may have 2-3.
- Only the last attempt reflects the terminal status; earlier attempts read FAILED.
- `msisdn` populated for mobile-money rails, `account_number` for bank rails (mutually exclusive); the other is null.
- `requested_at` is an ISO-Z **string** (text); `completed_at` is a proper timestamptz (null if PENDING) — mixed types.
- `response_code` is `00` on success, else partner-specific codes (E51, TIMEOUT, INVALID_ACC, E91).
- `raw_response` is a jsonb blob; `attempt_id` is a generated surrogate serial.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| attempt_id | bigint | no | Primary key (surrogate serial) |
| transfer_id | uuid | no | -> transfers.transfer_id |
| attempt_no | integer | no | Attempt sequence number |
| partner | text | no | Payout partner (Flutterwave, Cellulant, ...) |
| rail | text | no | Payout rail |
| partner_reference | text | no | Partner-side reference id |
| msisdn | text | yes | Target mobile-money number (bank rows null) |
| account_number | text | yes | Target bank account (mobile rows null) |
| status | text | no | SUCCESS / FAILED / PENDING |
| response_code | text | no | `00` on success else partner code |
| response_message | text | no | Partner response message |
| requested_at | text | no | ISO-Z string timestamp (not tz) |
| completed_at | timestamptz | no | Completion time (null if PENDING) |
| raw_response | jsonb | no | Partner response blob |

## Joins / lineage
- `transfer_id` -> transfers.transfer_id (child table).
