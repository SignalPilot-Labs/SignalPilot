# raw_marqeta.card_transactions

**Source system:** Marqeta (Transactions API)
**Grain:** one row per card transaction event (auth / clearing / refund / reversal)
**Approx rows (demo scale):** ~190k
**Loaded by:** warehouse/generators/gen_raw_marqeta.py

## Business definition
Every authorization, clearing, refund, and reversal on a NALA-issued card. 'NALA TOPUP' merchant rows that carry a `nala_transfer_id` represent card spend that funds a transfer. Feeds spend analytics and interchange.

## Known data-quality quirks
- `user_transaction_time` is an ISO-8601 **offset string**; `settlement_date` is `YYYY-MM-DD` (sparse, only when settled).
- `amount` is MAJOR units; refunds/reversals are negative.
- `state` enum: PENDING/CLEARED/COMPLETION/DECLINED/ERROR; declined rows null approval_code.
- `user_token` denormalized onto the transaction (matches the card's cardholder).
- `nala_transfer_id` sparse and occasionally UPPERCASE (dirty).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| token | text | no | transaction token (PK) |
| type | text | no | authorization/...clearing/refund/... |
| state | text | no | PENDING/CLEARED/COMPLETION/DECLINED/ERROR |
| user_token | text | no | -> cardholders.token (denormalized) |
| card_token | text | no | -> cards.token |
| amount | numeric(18,2) | no | MAJOR units, signed |
| currency_code | text | no | GBP/USD/EUR |
| approval_code | text | no | sparse |
| response_code | text | no | gateway code |
| response_memo | text | no | free text |
| network | text | no | VISA/MASTERCARD/PULSE/MAESTRO |
| acquirer_mid | text | no | merchant id |
| merchant_name | text | yes | merchant free text |
| mcc | text | no | merchant category code |
| merchant_country | text | no | merchant country |
| is_recurring | boolean | no | |
| nala_transfer_id | text | no | uuid of related transfer (dirty, sparse) |
| funding_source_token | text | no | -> funding_sources.token |
| user_transaction_time | text | no | ISO-8601 offset string |
| settlement_date | text | no | date string, sparse |

## Joins / lineage
- `card_token` -> `raw_marqeta.cards.token`; `user_token` -> `cardholders.token`.
- `funding_source_token` -> `funding_sources.token`; `nala_transfer_id` -> core transfers (lowercase first).
