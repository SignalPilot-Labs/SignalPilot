# raw_mpesa.callbacks

**Source system:** Safaricom M-PESA Daraja API (async result callbacks to our ResultURL/CallBackURL)
**Grain:** one row per async callback received (polymorphic across STK / B2C / status / balance)
**Approx rows (demo scale):** ~780k
**Loaded by:** warehouse/generators/gen_raw_mpesa.py

## Business definition
Raw async result notifications Daraja POSTs after an STK push or B2C payout
resolves. This is the source of truth for the final `ResultCode` that
back-fills the corresponding request row. Polymorphic: `callback_type`
discriminates STK vs B2C.

## Known data-quality quirks
- `callback_type` discriminates payload shape (`stk` callbacks fill `CheckoutRequestID`/`MerchantRequestID`; `b2c` fill `ConversationID`/`OriginatorConversationID`).
- Daraja occasionally double-posts: ~2% of B2C callbacks are duplicates (`is_duplicate = true`) — dedupe on the conversation id.
- `received_at_ms` is epoch **milliseconds**.
- `ResultParameters` holds the `{"ResultParameter":[{Key,Value}...]}` blob, NULL on failure.
- Pending requests have no callback row at all (missing, not NULL).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| callback_id | bigint | no | PK (synthetic) |
| callback_type | text | no | stk / b2c / status / balance |
| ConversationID / OriginatorConversationID | text | no | B2C join keys |
| CheckoutRequestID / MerchantRequestID | text | no | STK join keys |
| ResultType | integer | no | Daraja result type |
| ResultCode | integer | no | 0 = success, else failure |
| ResultDesc | text | no | result text |
| TransactionID | text | no | M-PESA receipt, success only |
| received_at_ms | bigint | no | epoch **ms** |
| is_duplicate | boolean | no | true for re-posted callbacks |
| ResultParameters | jsonb | no | key/value result blob |
| raw_payload | jsonb | no | full vendor blob |

## Joins / lineage
- Joins to `raw_mpesa.b2c_requests` on `OriginatorConversationID`/`ConversationID`.
- Joins to `raw_mpesa.stk_push_requests` on `CheckoutRequestID`/`MerchantRequestID`.
- Dedupe `is_duplicate = false` before counting outcomes.
