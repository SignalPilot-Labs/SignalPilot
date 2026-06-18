# raw_core_transfers.fx_quotes

**Source system:** internal core product DB (Postgres)
**Grain:** one row per FX rate lock backing a quote
**Approx rows (demo scale):** ~3,000,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The foreign-exchange detail behind a quote: mid-market rate, customer rate, margin, rate source, and validity window. One fx_quote is generated per converting quote/transfer.

## Known data-quality quirks
- `created` and `valid_until` are epoch-milliseconds **bigint**, not timestamps — divide by 1000 before converting.
- `rate_source` is either `internal` or `OpenExchange`.
- Generated only for converting transfers (orphan quotes have no fx_quote row).
- `fx_quote_id` is `det_uuid(("fxquote", i))`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| fx_quote_id | uuid | no | Primary key |
| quote_id | uuid | no | -> quotes.quote_id |
| base_currency | text | no | Base (send) currency |
| quote_currency | text | no | Quote (receive) currency |
| mid_market_rate | numeric(18,8) | no | Mid-market reference rate |
| customer_rate | numeric(18,8) | no | Rate offered to the customer |
| margin_bps | integer | no | Margin over mid in basis points |
| rate_source | text | no | internal / OpenExchange |
| locked | boolean | no | Whether the rate was locked |
| created | bigint | no | Creation time as epoch milliseconds |
| valid_until | bigint | no | Expiry time as epoch milliseconds |

## Joins / lineage
- `quote_id` -> quotes.quote_id (and transitively transfers via quotes.transfer_id).
