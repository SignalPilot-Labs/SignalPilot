# raw_rafiki.collections

**Source system:** Rafiki chain-listener / collections service
**Grain:** one row per inbound stablecoin collection
**Approx rows (demo scale):** ~tens of thousands (1,095 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Inbound stablecoin (USDC/USDT/PYUSD) received from a merchant's payers, on one of
several chains. Each collection is converted to a USD value, fee-charged, and later
swept into a daily settlement. A core Rafiki fact table on the collect side.

## Known data-quality quirks
- `status` has legacy value `'CONFIRMED_OLD'` (means confirmed).
- `received_at` is an ISO-Z string; `confirmed_at` is epoch milliseconds (~10% null).
- `settlement_id` is null at raw (settlement linkage derived downstream by merchant/date).
- `from_wallet` is a crypto wallet address (PII).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| collection_id | text | no | PK, `col_<hex>` |
| merchant_id | text | no | Owning merchant |
| reference | text | no | Merchant idempotency ref |
| stablecoin | text | no | USDC/USDT/PYUSD |
| chain | text | no | ethereum/polygon/tron/solana/base |
| amount_crypto | numeric | no | Amount in stablecoin units |
| amount_usd | numeric | no | USD value |
| fee_usd | numeric | no | Collection fee |
| from_wallet | text | yes | Payer wallet address |
| to_wallet | text | no | Rafiki deposit wallet |
| tx_hash | text | no | On-chain tx hash |
| confirmations | integer | no | Chain confirmations |
| status | text | no | confirmed/pending/failed/CONFIRMED_OLD |
| rate_card_id | text | no | Pricing card applied |
| settlement_id | text | no | Settlement (null at raw) |
| received_at | text | no | ISO-Z string |
| confirmed_at | bigint | no | Epoch ms (sparse) |
| metadata | jsonb | no | Vendor payload |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; `rate_card_id` -> `rate_cards`.
- Rolls into `raw_rafiki.settlements` / `settlement_lines` and `balance_transactions` by merchant+date.
