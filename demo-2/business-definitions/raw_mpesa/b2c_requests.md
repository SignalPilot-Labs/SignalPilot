# raw_mpesa.b2c_requests

**Source system:** Safaricom M-PESA Daraja API (B2C — /mpesa/b2c/v1/paymentrequest)
**Grain:** one row per B2C payout request (NALA crediting a recipient's M-PESA wallet)
**Approx rows (demo scale):** ~540k (18% of transfers route to KE/TZ M-PESA)
**Loaded by:** warehouse/generators/gen_raw_mpesa.py

## Business definition
The primary M-PESA payout leg. When a NALA transfer is destined for a Kenyan or
Tanzanian M-PESA wallet, NALA calls Daraja B2C to disburse funds from its
shortcode to the recipient MSISDN. The request is accepted synchronously
(`ResponseCode`) and the final outcome arrives asynchronously via a callback
(see `callbacks`), which back-fills `ResultCode`/`TransactionID`.

## Known data-quality quirks
- Daraja CamelCase field naming throughout (`OriginatorConversationID`, `PartyB`).
- `ResultCode`/`ResultDesc`/`TransactionReceipt` are NULL until the callback lands; ~3% of rows stay pending forever.
- `TransactionCompletedDateTime` uses `dd.MM.yyyy HH:mm:ss` (different from every other M-PESA date format) and is NULL for non-success.
- `ReceiverPartyPublicName` is masked by Daraja: `2547****1234 - JOHN D.`.
- `PartyB` (recipient MSISDN) is dirtied via `dirty_phone` (00 prefix / spaces / no +).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| OriginatorConversationID | text | no | PK; our idempotency id `AG_<ts>_<hash>` |
| ConversationID | text | no | Daraja-assigned conversation id |
| TransactionID | text | no | M-PESA receipt, success only |
| InitiatorName | text | no | API initiator username |
| CommandID | text | no | BusinessPayment / SalaryPayment / PromotionPayment |
| Amount | numeric(18,2) | no | payout amount (KES/TZS) |
| PartyA | text | no | NALA shortcode |
| PartyB | text | yes | recipient MSISDN (dirty format) |
| Remarks / Occasion | text | no | free text, sparse |
| ResponseCode / ResponseDescription | text | no | sync accept ("0") |
| ResultCode | integer | no | final result, NULL until callback |
| ResultDesc | text | no | final result text |
| TransactionReceipt / TransactionAmount | text/numeric | no | success only |
| B2CRecipientIsRegisteredCustomer | text | no | "Y"/"N" |
| B2C*AvailableFunds | numeric(18,2) | no | shortcode float balances |
| ReceiverPartyPublicName | text | yes | masked recipient name+MSISDN |
| TransactionCompletedDateTime | text | no | `dd.MM.yyyy HH:mm:ss`, success only |
| nala_transfer_id | uuid | no | soft ref to core transfers |
| nala_customer_code | text | no | soft ref `CUS_########` |
| currency | text | no | KES or TZS |
| created | timestamptz | no | our ingest time |
| raw_payload | jsonb | no | full vendor result blob |

## Joins / lineage
- Joins to `raw_mpesa.callbacks` on `OriginatorConversationID`/`ConversationID` (callback carries the final ResultCode).
- Joins to `raw_core_transfers.transfers` on `nala_transfer_id` (soft, not enforced; a random subset of transfers).
- `nala_customer_code` resolves to `common.customer_master()` code.
