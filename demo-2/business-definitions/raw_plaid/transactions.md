# raw_plaid.transactions

**Source system:** Plaid (Transactions API)
**Grain:** one row per bank transaction on a linked account
**Approx rows (demo scale):** ~200k
**Loaded by:** warehouse/generators/gen_raw_plaid.py

## Business definition
The transaction feed from a user's linked bank account. NALA-originated debits (merchant 'NALA') represent ACH funding pulls for transfers; `nala_transfer_id` links those to the transfer. Other rows give spend context for risk.

## Known data-quality quirks
- `date`/`authorized_date` are `YYYY-MM-DD` **strings**; `created_at` is ISO-8601.
- `amount` is MAJOR units; **Plaid sign convention: positive = money OUT** of the account.
- `category` is a legacy comma-separated list; `personal_finance_category` is the new taxonomy.
- `pending` is true when `pending_transaction_id` is set (~8%).
- `nala_transfer_id` sparse and occasionally UPPERCASE (dirty).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| transaction_id | text | no | opaque (PK) |
| account_id | text | no | -> accounts.account_id |
| item_id | text | no | -> items.item_id |
| amount | numeric(18,2) | no | MAJOR units, +=out |
| iso_currency_code | text | no | GBP/USD/EUR |
| date | text | no | posted date string |
| authorized_date | text | no | auth date string, sparse |
| name | text | no | raw description |
| merchant_name | text | no | cleaned, sparse |
| payment_channel | text | no | online/in store/other |
| pending | boolean | no | pending flag |
| category | text | no | legacy comma list |
| personal_finance_category | text | no | new taxonomy primary |
| pending_transaction_id | text | no | links pending->posted, sparse |
| nala_transfer_id | text | no | uuid of funded transfer (dirty, sparse) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `account_id` -> `raw_plaid.accounts.account_id`.
- `nala_transfer_id` -> core `transfers.transfer_id` (lowercase first).
