# raw_rafiki.invoice_line_items

**Source system:** Rafiki billing service
**Grain:** one row per line on an invoice
**Approx rows (demo scale):** ~thousands (789 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Detail lines that make up an invoice subtotal: collection fees, payout fees, FX margin
and platform subscription. Each has a quantity and unit amount that multiply to the
line amount.

## Known data-quality quirks
- `line_item_id` is `<invoice_id>_li<n>` (composite, deterministic).
- Line amounts sum to the parent invoice subtotal (allocated, last line absorbs rounding).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| line_item_id | text | no | PK |
| invoice_id | text | no | Parent invoice |
| merchant_id | text | no | Owning merchant |
| item_type | text | no | collection_fees/payout_fees/fx_margin/platform_fee |
| description | text | no | Line description |
| quantity | integer | no | Units |
| unit_amount_usd | numeric | no | Per-unit amount |
| amount_usd | numeric | no | Line total |
| created_at | timestamptz | no | Line creation time |

## Joins / lineage
- Joins to `raw_rafiki.invoices` on `invoice_id`.
