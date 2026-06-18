# raw_flutterwave.beneficiaries

**Source system:** Flutterwave v3 API (/beneficiaries)
**Grain:** one row per saved payout destination
**Approx rows (demo scale):** ~30k
**Loaded by:** warehouse/generators/gen_raw_flutterwave.py

## Business definition
Saved Flutterwave payout destinations (bank account or mobile-money wallet) tied
to NALA recipients. Heavy PII: holder name, account number / MSISDN, email, phone.

## Known data-quality quirks
- `full_name` vs `beneficiary_name` is a classic dirty near-dup: ~20% uppercased, ~15% name order swapped, ~15% NULL.
- `account_number` is a bank acct for banks, an MSISDN for mobile-money (`account_bank` resolves which).
- `email` dirtied (`dirty_email`: casing/space/dot drift) and ~25% NULL; `mobilenumber` dirtied (`dirty_phone`) and ~20% NULL.
- `created_at` is an ISO-Z string. Soft-delete via `is_deleted` (~5%).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK |
| account_number | text | yes | bank acct OR MSISDN |
| account_bank | text | no | bank code |
| bank_name | text | no | institution name |
| full_name | text | yes | holder name (clean) |
| beneficiary_name | text | yes | dirty near-dup of full_name |
| email | text | yes | dirty / sparse |
| mobilenumber | text | yes | MSISDN, dirty / sparse |
| currency / country | text | no | receive market |
| nala_customer_code | text | no | soft ref `CUS_########` |
| nala_recipient_uuid | uuid | no | soft ref to core recipient |
| is_deleted | boolean | no | soft-delete flag |
| meta | jsonb | no | source/verification metadata |
| created_at | text | no | ISO-Z string |

## Joins / lineage
- Referenced by `raw_flutterwave.transfers.beneficiary_id` (soft, same schema).
- `nala_customer_code` → `customer_master()` code; `nala_recipient_uuid` → core recipients (soft).
