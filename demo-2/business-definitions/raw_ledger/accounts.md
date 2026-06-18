# raw_ledger.accounts

**Source system:** internal core ledger service
**Grain:** one row per general-ledger account (incl. per-customer wallet liability accounts)
**Approx rows (demo scale):** ~220 (17 GL + ~200 customer)
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
NALA's chart of accounts. Includes operating cash, crypto custody asset accounts (Fireblocks/Circle), customer-balance liability accounts, fee/FX revenue, and partner-cost expense accounts. Customer wallet accounts carry `customer_code` (`CUS_...`) to tie a balance to a person.

## Known data-quality quirks
- ~5% of customer accounts are soft-deleted (`is_deleted=true`, `deleted_at` set).
- `parent_account_id` is self-referential and null for top-level accounts.
- `customer_code` is null for all GL/treasury accounts.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| account_id | bigint | no | PK |
| account_code | text | no | e.g. 1000-CASH-USD, 2000-CUST-CUS_00000123 |
| account_name | text | no | Display name |
| account_type_id | integer | no | -> account_types.account_type_id |
| currency | text | no | Account currency (fiat or stablecoin) |
| parent_account_id | bigint | no | Self-reference, nullable |
| customer_code | text | yes | CUS_... when a customer wallet account; links to customer_master |
| is_contra | boolean | no | Contra-account flag |
| is_active | boolean | no | Active flag |
| is_deleted | boolean | no | Soft-delete flag |
| deleted_at | timestamptz | no | When soft-deleted |
| created_at | timestamptz | no | Creation ts (internal ISO) |
| updated_at | timestamptz | no | Last update |
| metadata | jsonb | no | Free-form |

## Joins / lineage
- `account_type_id` -> raw_ledger.account_types.
- `customer_code` -> customer_master (`CUS_...`); cross-source join key (clean here).
