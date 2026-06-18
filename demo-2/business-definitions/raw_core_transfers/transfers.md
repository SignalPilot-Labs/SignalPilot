# raw_core_transfers.transfers

**Source system:** internal core product DB (Postgres)
**Grain:** one row per money transfer (send) initiated by a customer
**Approx rows (demo scale):** ~3,000,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The central FACT table of the NALA product: each row is a single remittance from a sending customer to a recipient over a corridor. It owns the canonical `transfer_id` space (`det_uuid(("transfer", i))`) that every other source system references. Amounts, applied FX rate/margin, funding and payout rails, status, and lifecycle timestamps all live here.

## Known data-quality quirks
- `status` is free-text, weighted ~88% `COMPLETED`; values include `COMPLETED`, `PENDING`, `FAILED`, `CANCELLED`, `REFUNDED`, plus the legacy `PENDING_OLD` enum that should be treated as pending.
- `completed_at` is NULL unless status is `COMPLETED` or `REFUNDED`; `funded_at` is generally populated. Timestamps drift forward from `created_at` (funded after created, completed after funded).
- `cancellation_reason_id` is sparse (only set when `status = CANCELLED`).
- `promo_code` is sparse (~15% populated; null otherwise).
- `recipient_id` references any recipient id in range and is NOT guaranteed to belong to the same `customer_id` (generator uses a cheap random pick) — join on `customer_id` for ownership, not via recipient.
- `raw_payload` is a jsonb blob (channel, app_version, promo); `source_ip` is an inet.
- `fee_amount` is often 0 for mobile-money rails; bank rails carry a fee.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| transfer_id | uuid | no | Primary key; canonical `det_uuid(("transfer", i))` referenced across all source systems |
| reference | text | no | Human reference, format `NALA-XXXXXXXX` |
| customer_id | bigint | no | Sending customer (canonical cid) -> customers.customer_id |
| recipient_id | bigint | no | Beneficiary -> recipients.recipient_id (not guaranteed same-customer) |
| corridor_id | bigint | no | -> corridors.corridor_id |
| send_country | text | no | Debit country |
| send_currency | text | no | Debit currency |
| receive_country | text | no | Credit country |
| receive_currency | text | no | Credit currency |
| send_amount | numeric(18,2) | no | Amount debited from sender |
| receive_amount | numeric(18,2) | no | Amount credited to recipient |
| fee_amount | numeric(18,2) | no | Fee charged (often 0 for mobile money) |
| fee_currency | text | no | Fee currency (= send_currency) |
| fx_rate | numeric(18,8) | no | Applied send->receive rate (mid minus margin) |
| mid_market_rate | numeric(18,8) | no | Mid-market reference rate |
| fx_margin_bps | integer | no | Markup over mid in basis points |
| status | text | no | COMPLETED/PENDING/FAILED/CANCELLED/REFUNDED/PENDING_OLD |
| rail | text | no | Payout rail used (M-PESA, Bank, MTN MoMo, ...) |
| payout_partner | text | no | Payout partner (Flutterwave, Thunes, ...) |
| funding_method | text | no | card / bank_transfer / open_banking / wallet |
| funding_partner | text | no | Stripe / Plaid / TrueLayer / NALA Wallet |
| promo_code | text | no | Applied promo code (sparse) |
| cancellation_reason_id | bigint | no | -> cancellation_reasons.reason_id (set when CANCELLED) |
| is_first_transfer | boolean | no | Whether this is the customer's first transfer |
| quote_id | uuid | no | -> quotes.quote_id (originating quote) |
| created_at | timestamptz | no | Initiation time |
| funded_at | timestamptz | no | Funding time |
| completed_at | timestamptz | no | Completion time (null unless COMPLETED/REFUNDED) |
| updated_at | timestamptz | no | Last update |
| source_ip | inet | yes | Originating IP address |
| raw_payload | jsonb | no | Denormalized internal/vendor blob |

## Joins / lineage
- `transfer_id` is the canonical key referenced by raw_mpesa / raw_stripe / raw_ledger and the other source systems via `det_uuid(("transfer", i))`.
- `customer_id` -> customers.customer_id (authoritative ownership join).
- `recipient_id` -> recipients.recipient_id (not ownership-safe).
- `corridor_id` -> corridors.corridor_id; `cancellation_reason_id` -> cancellation_reasons.reason_id; `quote_id` -> quotes.quote_id.
- Child tables keyed on `transfer_id`: transfer_legs, transfer_status_history, transfer_fees, payout_attempts.
