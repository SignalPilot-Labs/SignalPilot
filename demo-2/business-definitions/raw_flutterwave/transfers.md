# raw_flutterwave.transfers

**Source system:** Flutterwave v3 API (/transfers)
**Grain:** one row per attempted payout to a beneficiary
**Approx rows (demo scale):** ~660k (22% of transfers route via Flutterwave)
**Loaded by:** warehouse/generators/gen_raw_flutterwave.py

## Business definition
The Flutterwave payout fact. Flutterwave is one of NALA's pan-African payout
rails, crediting recipient bank accounts or mobile-money wallets across NG, GH,
UG, RW, SN, CI, CM, GA, CG, ZA (and overlap into KE/TZ). One row per payout
attempt; terminal status arrives via `webhooks`.

## Known data-quality quirks
- Flutterwave snake_case naming (deliberately different from M-PESA CamelCase).
- `status` enum `NEW`/`PENDING`/`SUCCESSFUL`/`FAILED` plus legacy stuck value `QUEUED`.
- `created_at` is an ISO-Z string; `date_created` is a redundant timestamptz copy that drifts by a few seconds.
- `bank_reference` NULL until settled (~14% never settle).
- `account_number` is a bank account number for banks, an MSISDN for mobile-money banks (`is_mobile_money`) — type overloaded.
- `fullname` here vs `beneficiaries.beneficiary_name` can disagree (dirty name resolution).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK; Flutterwave transfer id |
| reference | text | no | our idempotency reference |
| account_number | text | yes | destination bank acct OR MSISDN |
| bank_code / bank_name | text | no | destination institution |
| fullname | text | yes | beneficiary name |
| amount / fee | numeric(18,2) | no | payout + Flutterwave fee |
| currency | text | no | receive currency |
| narration | text | no | payout description |
| status | text | no | NEW/PENDING/SUCCESSFUL/FAILED/legacy QUEUED |
| complete_message | text | no | provider message |
| requires_approval / is_approved | integer | no | 0/1 flags |
| bank_reference | text | no | destination ref, NULL until settled |
| meta | jsonb | no | provider metadata |
| beneficiary_id | bigint | no | ref `beneficiaries.id` (same-schema, soft) |
| nala_transfer_id | uuid | no | soft ref to core transfers |
| nala_customer_code | text | no | soft ref `CUS_########` |
| recipient_phone | text | yes | recipient MSISDN (dirty), sparse |
| debit_currency | text | no | USD / USDC / GBP / EUR |
| created_at | text | no | ISO-Z string |
| date_created | timestamptz | no | drifted ingest copy |
| raw_payload | jsonb | no | vendor `{data:{...}}` blob |

## Joins / lineage
- Joins to `raw_flutterwave.beneficiaries` on `beneficiary_id` (soft).
- Joins to `raw_flutterwave.webhooks` / `transfer_retries` on `id`.
- `nala_transfer_id` → `raw_core_transfers.transfers` (soft, random subset).
