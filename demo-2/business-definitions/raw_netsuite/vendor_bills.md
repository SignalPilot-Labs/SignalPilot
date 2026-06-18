# raw_netsuite.vendor_bills

**Source system:** Oracle NetSuite — Vendor Bill (AP transaction)
**Grain:** one row per vendor bill (AP invoice header)
**Approx rows (demo scale):** ~150,000 (`N["transfers"] / 20`)
**Loaded by:** warehouse/generators/gen_raw_netsuite.py

## Business definition
Accounts-payable bills NALA owes its vendors. Captures gross amount, tax, base-currency amount, payment progress (`amount_paid`/`amount_remaining`) and approval workflow status. Used for AP aging, spend, and cash-out forecasting.

## Known data-quality quirks
- `status` is free text (Paid In Full / Open / Pending Approval / Cancelled) and overlaps with `approval_status`.
- `amount_base` is gross (amount + tax) converted at `exchange_rate`; `exchange_rate` = 1.0 for GBP/USD.
- `department_id` sparse. Cancelled bills can still carry amounts.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| bill_id | bigint | no | NetSuite internalId (PK) |
| tranid | text | no | bill document number |
| vendor_id | bigint | no | -> vendors.vendor_id |
| subsidiary_id | bigint | no | -> subsidiaries.subsidiary_id |
| department_id | bigint | no | -> departments (sparse) |
| trandate | date | no | bill date |
| duedate | date | no | due date |
| period_name | text | no | accounting period |
| currency | text | no | bill currency |
| exchange_rate | numeric(18,8) | no | rate to base currency |
| amount | numeric(18,2) | no | net bill amount (currency) |
| tax_amount | numeric(18,2) | no | tax amount |
| amount_base | numeric(18,2) | no | gross in subsidiary base ccy |
| amount_paid | numeric(18,2) | no | amount paid to date |
| amount_remaining | numeric(18,2) | no | outstanding amount |
| status | text | no | free-text bill status |
| approval_status | text | no | Approved/Pending/Rejected |
| memo | text | no | free text (sparse) |
| created_at | timestamptz | no | created |
| updated_at | timestamptz | no | last updated |

## Joins / lineage
- Joins to `vendors` on `vendor_id`, `subsidiaries` on `subsidiary_id`.
