# raw_rafiki.balance_transactions

**Source system:** Rafiki ledger service
**Grain:** one row per balance movement
**Approx rows (demo scale):** ~tens of thousands (2,400 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
The movement-level ledger behind a merchant's balance: collections credit, payouts and
fees debit. Amounts are signed and a `running_balance` is carried per merchant in event
order. Built from the same confirmed collections / paid payouts that drive settlements.

## Known data-quality quirks
- `amount` is signed (+ credit, - debit).
- `created_at` is epoch milliseconds (ledger service).
- `source_id` references a `collection_id`, `payout_id` or `invoice_id`.
- Fee transactions are interleaved after some movements.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| balance_txn_id | text | no | PK, `btxn_<hex>` |
| merchant_id | text | no | Owning merchant |
| currency | text | no | Ledger currency (USD) |
| type | text | no | collection/payout/fee/fx/adjustment/payout_reversal |
| amount | numeric | no | Signed amount |
| running_balance | numeric | no | Balance after this movement |
| source_id | text | no | collection_id/payout_id/invoice_id |
| description | text | no | Movement description |
| created_at | bigint | no | Epoch ms |
| metadata | jsonb | no | Vendor payload |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`.
- `source_id` -> `collections` / `payouts` / `invoices`.
