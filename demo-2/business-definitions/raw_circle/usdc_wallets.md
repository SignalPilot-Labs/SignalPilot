# raw_circle.usdc_wallets

**Source system:** Circle (Programmable Wallets / Payments API)
**Grain:** one row per Circle wallet (merchant or end-user)
**Approx rows (demo scale):** 250
**Loaded by:** warehouse/generators/gen_raw_circle.py

## Business definition
USDC wallets held with Circle. One `merchant` wallet is NALA's own collection wallet; the rest are `end_user_wallet`s tied to customers via `customer_ref`. Hosted wallets have no on-chain address; blockchain wallets carry `address`/`chain`.

## Known data-quality quirks
- `create_date`/`update_date` are ISO-Z STRINGS (text).
- `customer_ref` ~12% null (dirty join key).
- `address`/`chain` null for hosted wallets (~40%).
- `address_tag` set only ~10% of the time.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| wallet_id | text | no | PK, Circle walletId |
| type | text | no | merchant / end_user_wallet |
| description | text | no | Free text |
| customer_ref | text | yes | CUS_... (dirty join key) |
| balance_usdc | numeric(20,6) | no | Current USDC balance |
| chain | text | no | ETH / MATIC / SOL / ALGO / null |
| address | text | yes | On-chain address (PII), null if hosted |
| address_tag | text | no | Memo/tag |
| create_date | text | no | ISO-Z string |
| update_date | text | no | ISO-Z string |
| raw_payload | jsonb | no | Raw vendor payload |

## Joins / lineage
- `wallet_id` <- usdc_transfers.source_wallet_id / usdc_payments.merchant_wallet_id.
- `customer_ref` -> customer_master.
