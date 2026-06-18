# raw_mpesa.transaction_status_queries

**Source system:** Safaricom M-PESA Daraja API (/mpesa/transactionstatus/v1/query)
**Grain:** one row per transaction-status query (reconciliation poll)
**Approx rows (demo scale):** ~65k
**Loaded by:** warehouse/generators/gen_raw_mpesa.py

## Business definition
When a B2C payout's callback never arrives, NALA's reconciliation job queries
Daraja for the transaction status. This table records those polls and their
resolved status — used to close out stuck/pending payouts.

## Known data-quality quirks
- `TransactionStatus` is free-text with a legacy value `PENDING_OLD` still present alongside `Completed`/`Failed`.
- `FinalisedTime` is `yyyyMMddHHmmss` string, NULL when not completed.
- `DebitPartyName`/`CreditPartyName` are masked by Daraja (PII).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| OriginatorConversationID | text | no | PK |
| ConversationID | text | no | Daraja conversation id |
| TransactionID | text | no | the receipt being queried |
| PartyA | text | no | shortcode |
| IdentifierType | text | no | "4" = shortcode |
| ResultCode | integer | no | query result code |
| ResultDesc | text | no | query result text |
| DebitPartyName / CreditPartyName | text | yes | masked counterparties |
| TransactionStatus | text | no | Completed / Failed / legacy PENDING_OLD |
| ReasonType | text | no | free text |
| FinalisedTime | text | no | `yyyyMMddHHmmss` string, sparse |
| Amount | numeric(18,2) | no | queried amount |
| queried_at | timestamptz | no | when we polled |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- Joins to `raw_mpesa.b2c_requests` on `TransactionID` (the receipt) or conversation ids.
