# raw_circle.usdc_transfers

**Source system:** Circle (Payments API)
**Grain:** one row per USDC transfer (wallet-to-wallet or on-chain)
**Approx rows (demo scale):** ~N["transfers"]/10 (600 at test)
**Loaded by:** warehouse/generators/gen_raw_circle.py

## Business definition
USDC movements via Circle — funding the merchant wallet, settling to customer wallets, or pushing on-chain to external addresses. `reference_id` links to an internal settlement/transfer.

## Known data-quality quirks
- `create_date`/`update_date` are ISO-Z STRINGS.
- `amount` is a decimal STRING — cast to numeric.
- `tx_hash` null unless status `complete`; `error_code` set when `failed`.
- `source_wallet_id` null when source is `blockchain`; `dest_address`/`dest_chain` set only when dest is `blockchain`.
- `reference_id` ~40% null (dirty join key).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, Circle transfer uuid |
| source_wallet_id | text | no | -> usdc_wallets.wallet_id (null if blockchain src) |
| source_type | text | no | wallet / blockchain |
| dest_type | text | no | wallet / blockchain |
| dest_address | text | yes | On-chain dest address |
| dest_chain | text | no | ETH / MATIC / SOL |
| amount | text | no | Decimal string, USDC |
| currency | text | no | USD |
| tx_hash | text | yes | On-chain hash (null until complete) |
| status | text | no | complete / pending / failed |
| error_code | text | no | Set when failed |
| reference_id | text | no | Internal settlement/transfer id |
| create_date | text | no | ISO-Z string |
| update_date | text | no | ISO-Z string |
| raw_payload | jsonb | no | Raw vendor payload |

## Joins / lineage
- `source_wallet_id` -> raw_circle.usdc_wallets.
- `reference_id` -> internal settlements (dirty).
