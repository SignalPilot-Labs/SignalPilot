# raw_flutterwave.banks

**Source system:** Flutterwave v3 API (/banks/:country)
**Grain:** one row per supported destination bank / mobile-money operator
**Approx rows (demo scale):** 18
**Loaded by:** warehouse/generators/gen_raw_flutterwave.py

## Business definition
Lookup of destination institutions Flutterwave can pay out to, per receive
country. Includes both banks (e.g. Access Bank, GTBank) and mobile-money
operators (M-PESA, MTN MoMo, Wave) flagged by `is_mobile_money`.

## Known data-quality quirks
- Mobile-money "banks" reuse symbolic codes (`MPS`, `MTN`, `WAVE`) rather than numeric bank codes.
- Same operator (e.g. MTN MoMo) appears once per country with a distinct `id`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | integer | no | PK; Flutterwave bank id |
| code | text | no | bank/operator code |
| name | text | no | institution name |
| country | text | no | ISO2 receive country |
| currency | text | no | local currency |
| is_mobile_money | boolean | no | true for momo operators |
| created_at | timestamptz | no | lookup load time |

## Joins / lineage
- `code` aligns to `transfers.bank_code` / `beneficiaries.account_bank` (lookup; not enforced).
