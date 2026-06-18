# raw_marqeta.cards

**Source system:** Marqeta (Cards API)
**Grain:** one row per issued card (virtual or physical)
**Approx rows (demo scale):** ~23k
**Loaded by:** warehouse/generators/gen_raw_marqeta.py

## Business definition
A NALA-issued Marqeta card tied to a cardholder. Stores last4 + a tokenized PAN reference (`pan_token`) — **never the full PAN**. Drives the card-spend product on the multi-currency wallet.

## Known data-quality quirks
- `created_time`/`expiration_time` are ISO-8601 **offset strings**; `expiration` is `MMYY`.
- `state` enum: ACTIVE/SUSPENDED/TERMINATED/UNACTIVATED; `state_reason` only on non-active.
- `barcode` ~70% null (physical only).
- Mostly VIRTUAL_PAN; some PHYSICAL_MSR.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| token | text | no | card token (PK) |
| user_token | text | no | -> cardholders.token |
| card_product_token | text | no | issued product |
| last_four | text | yes | card last 4 |
| pan_token | text | yes | tokenized PAN reference (no full PAN) |
| expiration | text | no | MMYY |
| expiration_time | text | no | ISO-8601 offset string |
| barcode | text | no | sparse |
| pin_is_set | boolean | no | |
| state | text | no | ACTIVE/SUSPENDED/TERMINATED/UNACTIVATED |
| state_reason | text | no | sparse |
| fulfillment_status | text | no | ISSUED/SHIPPED/... |
| instrument_type | text | no | VIRTUAL_PAN/PHYSICAL_MSR |
| created_time | text | no | ISO-8601 offset string |

## Joins / lineage
- `user_token` -> `raw_marqeta.cardholders.token`.
- `token` referenced by `card_transactions.card_token`.
