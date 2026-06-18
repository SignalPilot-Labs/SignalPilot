# raw_fireblocks.vault_transactions

**Source system:** Fireblocks (custody API)
**Grain:** one row per Fireblocks transaction (transfer/mint/burn)
**Approx rows (demo scale):** ~N["transfers"]/12 (500 at test)
**Loaded by:** warehouse/generators/gen_raw_fireblocks.py

## Business definition
On-chain and internal custody movements of stablecoin treasury. Drives the FIREBLOCKS reconciliation. `referenceId` links to an internal settlement/transfer; `customerRefId` ties to a customer.

## Known data-quality quirks
- `createdAt` and `lastUpdated` are epoch MILLISECONDS (bigint) — convert with `to_timestamp(createdAt/1000.0)`.
- `amount`, `netAmount`, `fee` are decimal STRINGS — cast to numeric.
- `txHash` is null unless status COMPLETED; `destinationId`/`destAddress` set per internal-vs-external.
- `customerRefId` ~60% null; `referenceId` ~50% null (dirty join keys).
- camelCase quoted column names.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK |
| assetId | text | no | -> supported_assets.asset_id |
| sourceId | text | no | Source vault id |
| destinationId | text | no | Dest vault id (null if external) |
| sourceAddress | text | yes | On-chain source address |
| destAddress | text | yes | On-chain dest address |
| amount | text | no | Decimal string |
| amountUSD | numeric(20,4) | no | USD value |
| netAmount | text | no | Decimal string (amount - fee) |
| fee | text | no | Network fee, decimal string |
| feeCurrency | text | no | Gas asset |
| txHash | text | yes | On-chain hash (null until COMPLETED) |
| operation | text | no | TRANSFER / MINT / BURN / TYPED_MESSAGE |
| status | text | no | COMPLETED / SUBMITTED / FAILED / CANCELLED |
| subStatus | text | no | Detailed sub-status |
| createdAt | bigint | no | epoch ms |
| lastUpdated | bigint | no | epoch ms |
| customerRefId | text | yes | CUS_... (dirty join key) |
| referenceId | text | no | Internal settlement/transfer id |
| raw_payload | jsonb | no | Raw vendor payload |

## Joins / lineage
- `assetId` -> raw_fireblocks.supported_assets.
- `sourceId`/`destinationId` -> raw_fireblocks.vault_accounts.id.
- `referenceId` -> internal settlements; `customerRefId` -> customer_master.
