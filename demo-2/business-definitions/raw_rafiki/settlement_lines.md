# raw_rafiki.settlement_lines

**Source system:** Rafiki settlement service
**Grain:** one row per line within a settlement
**Approx rows (demo scale):** ~tens of thousands (1,846 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
The individual collection, payout, fee or adjustment entries that roll up into a
settlement. Each line points back to its source transaction and carries a credit/debit
direction so a settlement can be reconstructed line by line.

## Known data-quality quirks
- `settlement_line_id` is `<settlement_id>_l<n>` (composite, deterministic).
- `source_id` points at a `collection_id` or `payout_id` depending on `line_type`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| settlement_line_id | text | no | PK |
| settlement_id | text | no | Parent settlement |
| merchant_id | text | no | Owning merchant |
| line_type | text | no | collection/payout/fee/adjustment |
| source_id | text | no | collection_id or payout_id |
| description | text | no | Line description |
| amount_usd | numeric | no | Line amount (USD) |
| direction | text | no | credit/debit |
| created_at | timestamptz | no | Line creation time |

## Joins / lineage
- Joins to `raw_rafiki.settlements` on `settlement_id`.
- `source_id` -> `collections.collection_id` or `payouts.payout_id` (by `line_type`).
