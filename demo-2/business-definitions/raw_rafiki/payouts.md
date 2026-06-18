# raw_rafiki.payouts

**Source system:** Rafiki payout service
**Grain:** one row per outbound B2B payout
**Approx rows (demo scale):** ~tens of thousands (1,046 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Outbound payouts a merchant makes in local currency to a recipient via a mobile-money
or bank rail, priced off a locked FX rate. The core Rafiki fact table on the pay side.
Some payouts land to people who are also NALA consumer-app customers (`canonical_cid`).

## Known data-quality quirks
- `status` has legacy value `'PENDING_OLD'` (means processing).
- `created` is epoch milliseconds (payout service); `completed_at` is an ISO string with no tz (null until paid).
- `recipient_account` is MSISDN / bank account / IBAN (PII).
- `fx_lock_id` null when no lock was used (~30%).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| payout_id | text | no | PK, `pyt_<hex>` |
| merchant_id | text | no | Owning merchant |
| idempotency_key | text | no | Caller idempotency key |
| recipient_name | text | yes | Beneficiary name |
| recipient_account | text | yes | MSISDN/bank acct/IBAN |
| recipient_type | text | no | mobile_money/bank |
| rail | text | no | M-PESA/MTN MoMo/Bank/... |
| destination_country | text | no | Receive country |
| currency | text | no | Local currency |
| amount_local | numeric | no | Amount in local ccy |
| amount_usd | numeric | no | USD value |
| fx_rate | numeric | no | Applied rate |
| fee_usd | numeric | no | Payout fee |
| fx_lock_id | text | no | Locked FX quote (sparse) |
| status | text | no | paid/processing/failed/reversed/PENDING_OLD |
| failure_reason | text | no | Set when failed |
| partner | text | no | Payout rail partner |
| settlement_id | text | no | Settlement (null at raw) |
| canonical_cid | bigint | no | App customer id when recipient is a B2C customer |
| created | bigint | no | Epoch ms |
| completed_at | text | no | ISO string, no tz (null until paid) |
| metadata | jsonb | no | Vendor payload |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; `fx_lock_id` -> `fx_locks`.
- Cross-source: `canonical_cid` -> canonical customer master.
- Rolls into `settlements` / `settlement_lines` and `balance_transactions` by merchant+date.
