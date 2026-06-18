# raw_rafiki.invoices

**Source system:** Rafiki billing service
**Grain:** one row per merchant per billing month
**Approx rows (demo scale):** ~thousands (263 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Monthly platform-fee invoices billed to merchants for collection fees, payout fees,
FX margin and platform subscription. Tracks issuance, amount due, amount paid and
payment status.

## Known data-quality quirks
- `paid_at` null unless `status = 'paid'`; `past_due` invoices may be partially paid.
- `tax_usd` is currently 0 across the board.
- `invoice_number` format `RAF-<year>-<merchantidx><month>`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| invoice_id | text | no | PK, `inv_<hex>` |
| merchant_id | text | no | Owning merchant |
| invoice_number | text | no | Human invoice number |
| period_start | date | no | Billing period start |
| period_end | date | no | Billing period end |
| currency | text | no | Invoice currency (USD) |
| subtotal_usd | numeric | no | Subtotal |
| tax_usd | numeric | no | Tax |
| total_usd | numeric | no | Total |
| amount_paid_usd | numeric | no | Amount paid |
| status | text | no | draft/open/paid/void/past_due |
| due_date | date | no | Payment due date |
| issued_at | timestamptz | no | Issue time |
| paid_at | timestamptz | no | Payment time (null unless paid) |
| pdf_url | text | no | Invoice PDF URL |
| metadata | jsonb | no | Vendor payload |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; parent of `invoice_line_items`.
