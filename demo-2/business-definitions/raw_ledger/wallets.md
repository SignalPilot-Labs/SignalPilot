# raw_ledger.wallets

**Source system:** internal core ledger service (treasury wallet registry)
**Grain:** one row per balance-holding wallet (customer or treasury)
**Approx rows (demo scale):** ~290 (test) / scales with customer accounts
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
Internal balance wallets backing the multi-currency account. Includes treasury/fee/suspense wallets and per-customer fiat + stablecoin (USDC) wallets. Each wallet maps to a GL account via `ledger_account_id`. Stablecoin wallets carry a crypto `address` and `chain`.

## Known data-quality quirks
- `address`/`chain` are null for fiat wallets, populated for stablecoin wallets.
- `customer_code` null for treasury/fee/suspense wallets.
- ~10% of customer wallets are FROZEN or CLOSED.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| wallet_id | bigint | no | PK |
| wallet_uuid | text | no | UUID |
| customer_code | text | yes | CUS_... for customer wallets |
| wallet_type | text | no | CUSTOMER / TREASURY / FEE / SUSPENSE |
| currency | text | no | Fiat or stablecoin |
| ledger_account_id | bigint | no | -> accounts.account_id |
| address | text | yes | Crypto wallet address (stablecoin only) |
| chain | text | no | ethereum / polygon / solana / null |
| status | text | no | ACTIVE / FROZEN / CLOSED |
| opened_at | timestamptz | no | Opened ts |
| closed_at | timestamptz | no | Closed ts (when CLOSED) |
| metadata | jsonb | no | Free-form |

## Joins / lineage
- `ledger_account_id` -> raw_ledger.accounts.
- `customer_code` -> customer_master.
- `wallet_id` <- raw_ledger.wallet_transactions.
