# raw_circle.usdc_payments

**Source system:** Circle (Payments API)
**Grain:** one row per fiat funding payment (card/ACH/wire/blockchain) or refund
**Approx rows (demo scale):** ~N["transfers"]/8 (750 at test)
**Loaded by:** warehouse/generators/gen_raw_circle.py

## Business definition
Inbound fiat collections that fund USDC into the merchant wallet (and refunds). Card payments store governed card PII (last4 + BIN only, never full PAN). `risk_score` is Circle's fraud score.

## Known data-quality quirks
- `amount` is a numeric here (unlike transfers which use a string) — vendor inconsistency.
- `create_date`/`update_date` are ISO-Z STRINGS.
- `card_last4`/`card_bin`/`card_network` populated only for `source_type='card'`.
- `risk_score` ~15% null; `customer_ref` ~10% null (dirty join key).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, Circle payment uuid |
| type | text | no | payment / refund |
| merchant_wallet_id | text | no | -> usdc_wallets.wallet_id |
| customer_ref | text | yes | CUS_... (dirty join key) |
| amount | numeric(20,2) | no | Payment amount |
| currency | text | no | USD / EUR / GBP |
| source_type | text | no | card / ach / wire / blockchain |
| card_last4 | text | yes | Last 4 of PAN (governed) |
| card_bin | text | yes | First 6 / BIN (governed) |
| card_network | text | no | VISA / MASTERCARD |
| status | text | no | paid / confirmed / pending / failed / refunded |
| risk_score | integer | no | Fraud score 0-100 (nullable) |
| fees | numeric(20,2) | no | Circle processing fee |
| description | text | no | Free text |
| create_date | text | no | ISO-Z string |
| update_date | text | no | ISO-Z string |
| raw_payload | jsonb | no | Raw vendor payload |

## Joins / lineage
- `merchant_wallet_id` -> raw_circle.usdc_wallets.
- `id` <- raw_circle.chargebacks.payment_id.
- `customer_ref` -> customer_master.
