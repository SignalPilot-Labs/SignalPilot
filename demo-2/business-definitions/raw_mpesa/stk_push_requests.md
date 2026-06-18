# raw_mpesa.stk_push_requests

**Source system:** Safaricom M-PESA Daraja API (STK Push / Lipa na M-PESA Online — /mpesa/stkpush/v1/processrequest)
**Grain:** one row per STK push (collection) request
**Approx rows (demo scale):** ~270k
**Loaded by:** warehouse/generators/gen_raw_mpesa.py

## Business definition
The M-PESA collection leg. NALA prompts a customer's phone (STK push) to authorise
a payment for wallet top-up / funding. The customer enters their M-PESA PIN; the
result returns asynchronously via a callback.

## Known data-quality quirks
- `TransactionDate` is the Daraja string format `yyyyMMddHHmmss` (no separators).
- `ResultCode` NULL until the callback; ~5% remain pending.
- Failures carry user-facing codes: 1032 "Request cancelled by user", 1037 "DS timeout", 2001 "Wrong PIN".
- `PhoneNumber` / `PartyA` (payer MSISDN) dirtied via `dirty_phone`.
- `AccountReference` (our customer code) is ~15% NULL.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| MerchantRequestID | text | no | PK; our request id |
| CheckoutRequestID | text | no | Daraja checkout id `ws_CO_...` |
| BusinessShortCode | text | no | NALA shortcode |
| TransactionType | text | no | CustomerPayBillOnline / CustomerBuyGoodsOnline |
| Amount | numeric(18,2) | no | collection amount |
| PartyA | text | yes | payer MSISDN |
| PartyB | text | no | shortcode |
| PhoneNumber | text | yes | payer MSISDN (dirty) |
| AccountReference | text | no | our customer code, sparse |
| TransactionDesc / CustomerMessage | text | no | free text |
| ResponseCode / ResponseDescription | text | no | sync accept |
| ResultCode | integer | no | final, NULL until callback |
| ResultDesc | text | no | final result text |
| MpesaReceiptNumber | text | no | receipt, success only |
| nala_transfer_id | uuid | no | soft ref to core transfers |
| nala_customer_code | text | no | soft ref `CUS_########` |
| TransactionDate | text | no | `yyyyMMddHHmmss` string |
| created_at | timestamptz | no | our ingest time |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- Joins to `raw_mpesa.callbacks` on `CheckoutRequestID`/`MerchantRequestID`.
- `nala_transfer_id` → `raw_core_transfers.transfers` (soft).
