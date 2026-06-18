# raw_ledger.journal_entries

**Source system:** internal core ledger service
**Grain:** one row per posted accounting event (entry header)
**Approx rows (demo scale):** ~3.5M (entries that produce N["ledger_lines"] lines)
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
The header for each double-entry posting. Every entry groups 2+ journal_lines whose debits equal credits. Entries originate from transfers, Rafiki settlements, fee accruals, FX margin recognition, treasury moves, and manual adjustments. `reference_id` links back to the originating business object.

## Known data-quality quirks
- `status` has a legacy lowercase value `'posted'` alongside `'POSTED'`.
- ~3% are reversals (`is_reversal=true`, `reverses_entry_id` set).
- `reference_id` is a dirty cross-source key: a transfer UUID (matches core_transfers `det_uuid(("transfer", i))`) or a settlement id; null for some manual entries.
- `legacy_batch_id` is deprecated and ~92% null.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| entry_id | bigint | no | PK |
| entry_uuid | text | no | UUID |
| entry_date | date | no | Accounting date |
| posted_at | timestamptz | no | Internal ISO timestamp |
| currency | text | no | Entry currency |
| source_system | text | no | transfers / rafiki / treasury / fees / fx / manual |
| reference_type | text | no | transfer / settlement / fee / fx / adjustment |
| reference_id | text | no | Originating object id (dirty join key) |
| description | text | no | Free text |
| status | text | no | POSTED / posted / DRAFT / REVERSED |
| is_reversal | boolean | no | Reversal flag |
| reverses_entry_id | bigint | no | Entry this reverses |
| created_by | text | no | Actor / job |
| metadata | jsonb | no | Free-form |
| legacy_batch_id | text | no | Deprecated, mostly null |

## Joins / lineage
- `entry_id` <- raw_ledger.journal_lines.entry_id (1:many).
- `reference_id` -> core transfers / Rafiki settlements (dirty; needs trimming/casing care).
