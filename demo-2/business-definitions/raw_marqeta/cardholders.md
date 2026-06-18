# raw_marqeta.cardholders

**Source system:** Marqeta (Users API)
**Grain:** one row per Marqeta user (a NALA cardholder)
**Approx rows (demo scale):** ~18k
**Loaded by:** warehouse/generators/gen_raw_marqeta.py

## Business definition
A Marqeta user is a NALA app user enrolled for a NALA-issued card (multi-currency wallet / spend product). Holds the cardholder PII and account status. `nala_customer_code` ties back to the canonical NALA customer.

## Known data-quality quirks
- Timestamps are ISO-8601 **with offset strings** (e.g. `2025-03-04T11:02:00+00:00`).
- `status` enum: ACTIVE/SUSPENDED/UNVERIFIED/LIMITED; `active` boolean mirrors ACTIVE.
- `birth_date` is `YYYY-MM-DD` string (~20% null).
- `uses_parent_account` is a deprecated/legacy flag (always false).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| token | text | no | user token uuid-ish (PK) |
| nala_customer_code | text | no | CUS_00000123 join key |
| first_name | text | yes | first name |
| last_name | text | yes | last name |
| email | text | yes | email (dirty) |
| phone | text | yes | phone (dirty) |
| birth_date | text | yes | DOB string, sparse |
| address1 | text | yes | street |
| city | text | yes | city |
| state | text | yes | state/region |
| postal_code | text | yes | postcode |
| country | text | no | country |
| active | boolean | no | mirrors status=ACTIVE |
| status | text | no | ACTIVE/SUSPENDED/UNVERIFIED/LIMITED |
| uses_parent_account | boolean | no | legacy/deprecated |
| created_time | text | no | ISO-8601 offset string |
| last_modified_time | text | no | ISO-8601 offset string |

## Joins / lineage
- `nala_customer_code` -> `common.customer_master().code`.
- `token` referenced by `cards.user_token`, `card_transactions.user_token`, `funding_sources.user_token`.
