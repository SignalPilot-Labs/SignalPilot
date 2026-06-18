# raw_core_transfers.recipient_payout_methods

**Source system:** internal core product DB (Postgres)
**Grain:** one row per payout method attached to a recipient (1-2 per recipient)
**Approx rows (demo scale):** ~150,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
How money reaches a recipient: mobile money (MSISDN) or bank (account number / IBAN). Each recipient has at least one method; some have a second. Heavily PII (destination account identifiers).

## Known data-quality quirks
- Mutually-exclusive population by `method_type`: mobile_money rows have `msisdn` populated and `bank_name`/`account_number`/`iban`/`swift_bic` null; bank rows are the inverse.
- `iban` and `swift_bic` are sparse even on bank rows (~85% null).
- `is_verified` true ~80% of the time.
- `provider` doubles as the rail name for mobile money and as the bank name source for bank rows.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| payout_method_id | bigint | no | Primary key |
| recipient_id | bigint | no | -> recipients.recipient_id |
| method_type | text | no | mobile_money / bank |
| rail | text | no | M-PESA / MTN MoMo / Bank / ... |
| provider | text | no | Safaricom / Equity Bank / ... |
| msisdn | text | yes | Mobile-money number (bank rows null) |
| bank_name | text | no | Bank name (mobile-money rows null) |
| account_number | text | yes | Bank account number (mobile-money rows null) |
| account_name | text | yes | Account holder name |
| iban | text | yes | IBAN (sparse, ~85% null) |
| swift_bic | text | no | SWIFT/BIC (sparse) |
| is_default | boolean | no | Default method flag |
| is_verified | boolean | no | Verified flag (~80% true) |
| created_at | timestamptz | no | Creation time |

## Joins / lineage
- `recipient_id` -> recipients.recipient_id.
