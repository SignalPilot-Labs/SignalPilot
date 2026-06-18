# raw_plaid.items

**Source system:** Plaid (Items API)
**Grain:** one row per Plaid Item (a NALA user's linked bank-institution connection)
**Approx rows (demo scale):** ~21k
**Loaded by:** warehouse/generators/gen_raw_plaid.py

## Business definition
A Plaid Item is the persistent link between a NALA user and one financial institution login, enabling account/balance refreshes, ACH funding (auth), and identity verification. `nala_customer_code` ties it back to the canonical NALA customer.

## Known data-quality quirks
- Timestamps are ISO-8601 **strings** (not epoch).
- `status` mixes current values with legacy `ITEM_LOGIN_REQUIRED`.
- `available_products`/`billed_products` are comma-separated free text.
- `nala_customer_email` is a dirty alternate join key (~10% null).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| item_id | text | no | opaque (PK) |
| institution_id | text | no | `ins_...` |
| institution_name | text | no | denormalized bank name |
| nala_customer_code | text | no | CUS_00000123 join key |
| nala_customer_email | text | yes | dirty alt join key |
| available_products | text | no | comma list |
| billed_products | text | no | comma list |
| status | text | no | good/login_required/legacy |
| consent_expiration_time | text | no | ISO string, sparse |
| error_code | text | no | sparse |
| created_at | text | no | ISO-8601 string |
| updated_at | text | no | ISO-8601 string |

## Joins / lineage
- `nala_customer_code` -> `common.customer_master().code`.
- `item_id` referenced by `accounts`, `auth_numbers`, `transactions`, `identity_data`.
