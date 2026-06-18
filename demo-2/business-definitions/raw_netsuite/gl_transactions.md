# raw_netsuite.gl_transactions

**Source system:** Oracle NetSuite — Transaction lines (SuiteAnalytics export)
**Grain:** one row per GL transaction line
**Approx rows (demo scale):** ~3,000,000 (sized off `N["transfers"]`)
**Loaded by:** warehouse/generators/gen_raw_netsuite.py

## Business definition
The posted general-ledger line detail across all transaction types (Journals, Vendor Bills, Payments, Invoices, Deposits). Each transaction (`transaction_id`) emits a balanced set of lines — debits equal credits per transaction — across subsidiaries and currencies. This is the financial fact table for the ERP domain.

## Known data-quality quirks
- Double-entry invariant: `SUM(debit) = SUM(credit)` per `transaction_id` (verified at load).
- `created_epoch_ms` is epoch milliseconds (bigint), not a timestamp; `trandate` is the clean posting date.
- `amount` is signed (debit positive, credit negative); `debit`/`credit` columns hold the unsigned split.
- `department_id` sparse (~40% NULL). `exchange_rate` = 1.0 for GBP/USD subsidiaries.
- `status` is free text mixing posting and document statuses (Open / Posted / Paid In Full / Pending Approval).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| transaction_line_id | text | no | "<transaction_id>-<line>" (PK) |
| transaction_id | bigint | no | NetSuite transaction internalId |
| tranid | text | no | document number (JE1023…) |
| transaction_type | text | no | Journal/VendBill/Payment/Invoice/Deposit |
| line_number | integer | no | line sequence |
| account_id | bigint | no | -> gl_accounts.account_id |
| subsidiary_id | bigint | no | -> subsidiaries.subsidiary_id |
| department_id | bigint | no | -> departments.department_id (sparse) |
| trandate | date | no | posting date |
| period_name | text | no | accounting period ("Jun 2026") |
| memo | text | no | free text (sparse) |
| debit | numeric(18,2) | no | debit amount (currency) |
| credit | numeric(18,2) | no | credit amount (currency) |
| amount | numeric(18,2) | no | signed line amount (base ccy) |
| currency | text | no | transaction currency |
| exchange_rate | numeric(18,8) | no | rate to subsidiary base ccy |
| posting | boolean | no | posted vs non-posting |
| status | text | no | free-text status |
| created_epoch_ms | bigint | no | epoch ms creation |

## Joins / lineage
- Joins to `gl_accounts` on `account_id`, `subsidiaries` on `subsidiary_id`, `departments` on `department_id`.
