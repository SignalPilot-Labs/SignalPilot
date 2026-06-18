# raw_marqeta.funding_sources

**Source system:** Marqeta (Funding Sources API)
**Grain:** one row per funding source (program-level GPA or per-cardholder wallet)
**Approx rows (demo scale):** ~18k + 3 program rows
**Loaded by:** warehouse/generators/gen_raw_marqeta.py

## Business definition
Where a NALA card draws funds. Three program-level rows are NALA's per-currency GPA program funding accounts (`user_token` null); the rest are per-cardholder wallet funding sources. Card transactions reference these via `funding_source_token`.

## Known data-quality quirks
- `created_time` is an ISO-8601 **offset string**.
- Program-level rows have null `user_token`.
- `name_on_account` ~30% null; `account_suffix` (last4) ~60% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| token | text | no | funding source token (PK) |
| user_token | text | no | -> cardholders.token (null = program) |
| type | text | no | gpa/program/ach |
| name | text | no | funding source name |
| name_on_account | text | yes | account holder name, sparse |
| account_suffix | text | yes | linked acct last4, sparse |
| active | boolean | no | |
| is_default_account | boolean | no | |
| currency_code | text | no | GBP/USD/EUR |
| created_time | text | no | ISO-8601 offset string |

## Joins / lineage
- `user_token` -> `raw_marqeta.cardholders.token` (when not program-level).
- `token` referenced by `card_transactions.funding_source_token`.
