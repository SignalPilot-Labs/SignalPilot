# raw_fireblocks.supported_assets

**Source system:** Fireblocks (custody API)
**Grain:** one row per asset enabled in the Fireblocks workspace
**Approx rows (demo scale):** 8
**Loaded by:** warehouse/generators/gen_raw_fireblocks.py

## Business definition
The catalog of crypto assets NALA can custody in Fireblocks — primarily stablecoins (USDC on multiple chains, USDT, PYUSD) plus the base/gas assets (ETH, MATIC, SOL). Used to interpret `vault_transactions.assetId` and token decimals.

## Known data-quality quirks
- `contract_address` is null for base assets (ETH/MATIC/SOL).
- Same logical stablecoin appears under multiple asset ids per chain (USDC, USDC_POLYGON, USDC_SOL).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| asset_id | text | no | PK, Fireblocks asset id |
| name | text | no | Display name |
| type | text | no | BASE_ASSET / ERC20 / SPL |
| contract_address | text | no | Token contract (on-chain, null for base) |
| native_asset | text | no | Gas asset (ETH/MATIC/SOL) |
| decimals | integer | no | Token decimals |

## Joins / lineage
- `asset_id` <- raw_fireblocks.vault_transactions.assetId / vault_accounts.assetId.
