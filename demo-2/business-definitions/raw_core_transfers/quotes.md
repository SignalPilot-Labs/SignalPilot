# raw_core_transfers.quotes

**Source system:** internal core product DB (Postgres)
**Grain:** one row per pricing quote requested by a customer
**Approx rows (demo scale):** ~3,300,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
A price quote a customer received for a prospective transfer (amounts, fee, FX rate, rail). Most quotes convert into a transfer; a tail of "orphan" quotes never convert. Used for conversion-funnel and pricing analysis.

## Known data-quality quirks
- Mix of converted quotes (one per transfer, ~3M) and orphan/non-converting quotes (~10% extra, ~300k) appended after.
- `converted = true` implies `transfer_id` is set; orphan quotes have `converted = false` and `transfer_id = NULL`.
- `expires_at` is typically 30 minutes after `created_at`.
- `quote_id` for converted quotes is `det_uuid(("quote", i))`; orphans use `det_uuid(("orphanquote", i))`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| quote_id | uuid | no | Primary key |
| customer_id | bigint | no | -> customers.customer_id |
| send_currency | text | no | Debit currency |
| receive_currency | text | no | Credit currency |
| send_amount | numeric(18,2) | no | Quoted send amount |
| receive_amount | numeric(18,2) | no | Quoted receive amount |
| fee_amount | numeric(18,2) | no | Quoted fee |
| fx_rate | numeric(18,8) | no | Quoted applied rate |
| rail | text | no | Payout rail |
| converted | boolean | no | Whether the quote became a transfer |
| transfer_id | uuid | no | -> transfers.transfer_id (null if not converted) |
| created_at | timestamptz | no | Quote time |
| expires_at | timestamptz | no | Expiry time (~30 min after created) |

## Joins / lineage
- `customer_id` -> customers.customer_id.
- `transfer_id` -> transfers.transfer_id; transfers.quote_id -> quotes.quote_id (1:1 for converted quotes).
- `quote_id` is referenced by fx_quotes.quote_id.
