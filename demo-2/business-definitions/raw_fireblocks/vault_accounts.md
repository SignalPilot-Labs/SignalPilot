# raw_fireblocks.vault_accounts

**Source system:** Fireblocks (custody API)
**Grain:** one row per Fireblocks vault account
**Approx rows (demo scale):** 60
**Loaded by:** warehouse/generators/gen_raw_fireblocks.py

## Business definition
A vault account is a logical custody container in Fireblocks. NALA runs treasury vaults (pooled custody) and customer-segregated vaults. `customerRefId` ties a segregated vault back to a customer. Column names follow Fireblocks' camelCase API style.

## Known data-quality quirks
- camelCase, quoted column names (`assetId`, `customerRefId`, `hiddenOnUI`, `createdAt`).
- `createdAt` is an ISO-Z STRING (text), not a timestamp.
- `customerRefId` ~15% null on customer vaults (dirty join key) and always null on treasury vaults.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, Fireblocks vault id (numeric-as-string) |
| name | text | no | Vault name |
| assetId | text | no | Primary asset |
| customerRefId | text | yes | CUS_... (dirty join key) |
| hiddenOnUI | boolean | no | Hidden flag |
| autoFuel | boolean | no | Auto gas-fueling flag |
| address | text | yes | Deposit address (crypto, PII) |
| createdAt | text | no | ISO-Z string |
| raw_payload | jsonb | no | Raw vendor payload |

## Joins / lineage
- `assetId` -> raw_fireblocks.supported_assets.asset_id.
- `customerRefId` -> customer_master (dirty; trim + casing).
