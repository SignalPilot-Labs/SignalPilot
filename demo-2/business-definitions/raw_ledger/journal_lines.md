# raw_ledger.journal_lines

**Source system:** internal core ledger service
**Grain:** one row per debit or credit line within a journal entry
**Approx rows (demo scale):** N["ledger_lines"] (8M demo / 14k test)
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
The fact table of the general ledger. Each line debits or credits exactly one account. The defining invariant: for every `entry_id`, the sum of DEBIT-line amounts equals the sum of CREDIT-line amounts (verified at generation: 0 unbalanced entries). `amount` is always positive; `direction` carries the sign.

## Known data-quality quirks
- Two representations of sign coexist: a normalized (`direction`, `amount`) pair AND denormalized `debit`/`credit` columns where exactly one is populated per row. Use one consistently.
- `line_no` is 1..n within an entry, not globally unique.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| line_id | bigint | no | PK |
| entry_id | bigint | no | -> journal_entries.entry_id |
| line_no | integer | no | Sequence within the entry |
| account_id | bigint | no | -> accounts.account_id |
| direction | text | no | DEBIT or CREDIT |
| amount | numeric(20,4) | no | Positive magnitude |
| currency | text | no | Line currency |
| debit | numeric(20,4) | no | = amount when DEBIT, else null |
| credit | numeric(20,4) | no | = amount when CREDIT, else null |
| memo | text | no | Free text |
| posted_at | timestamptz | no | Posting timestamp (matches entry) |

## Joins / lineage
- `entry_id` -> raw_ledger.journal_entries.
- `account_id` -> raw_ledger.accounts.
