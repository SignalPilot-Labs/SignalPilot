# raw_rafiki.settlements

**Source system:** Rafiki settlement service
**Grain:** one row per merchant per settlement day
**Approx rows (demo scale):** ~tens of thousands (1,105 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Daily netting of a merchant's confirmed collections against its paid/processing
payouts, less fees. Produces a net amount owed to/from the merchant and a downloadable
statement. Built deterministically by grouping collections + payouts by merchant+date.

## Known data-quality quirks
- `settled_at` only set when `status = 'settled'`.
- `currency` is the merchant's settlement currency, not necessarily the payout currency.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| settlement_id | text | no | PK, `set_<hex>` |
| merchant_id | text | no | Owning merchant |
| settlement_date | date | no | Settlement day |
| currency | text | no | Settlement currency |
| gross_collected_usd | numeric | no | Sum of collections (USD) |
| gross_paid_out_usd | numeric | no | Sum of payouts (USD) |
| total_fees_usd | numeric | no | Fees |
| net_amount_usd | numeric | no | Collected - paid - fees |
| line_count | integer | no | Number of settlement lines |
| status | text | no | settled/pending/on_hold |
| statement_url | text | no | PDF statement URL |
| created_at | timestamptz | no | Batch creation time |
| settled_at | timestamptz | no | Settlement completion (null until settled) |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; parent of `settlement_lines`.
- Lines reference underlying `collections.collection_id` / `payouts.payout_id`.
