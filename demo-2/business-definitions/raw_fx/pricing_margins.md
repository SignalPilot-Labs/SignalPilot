# raw_fx.pricing_margins

**Source system:** NALA internal pricing service config
**Grain:** one row per (send currency, receive currency, customer segment, effective period)
**Approx rows (demo scale):** ~117
**Loaded by:** warehouse/generators/gen_raw_fx.py

## Business definition
The FX margin (markup over the mid rate, in basis points) NALA applies per
currency-corridor and customer segment. This is NALA's primary monetization
lever on the consumer side (~0.5-1.5% per the company profile). Rows are
effective-dated; a corridor can have a superseded historical row plus a current
row (`effective_to IS NULL`). Segments: consumer, rafiki (B2B), vip.

## Known data-quality quirks
- SCD-style: some corridors have a closed historical period plus an open current row; filter `effective_to IS NULL` for the live margin.
- Soft delete: ~5% of rows have `is_deleted=true` with a `deleted_at`; exclude them for live pricing.
- `min/max_margin_bps` are guardrails, not the applied value (`margin_bps` is applied).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| margin_id | integer | no | PK. |
| send_currency | text | no | Debit currency (GBP/USD/EUR). |
| receive_currency | text | no | Credit currency. |
| customer_segment | text | no | consumer / rafiki / vip. |
| margin_bps | numeric(10,4) | no | Applied FX markup over mid, in basis points. |
| min_margin_bps | numeric(10,4) | no | Lower guardrail. |
| max_margin_bps | numeric(10,4) | no | Upper guardrail. |
| effective_from | date | no | Start of the rate's validity. |
| effective_to | date | no | End of validity; NULL = currently active. |
| is_deleted | boolean | no | Soft-delete flag. |
| deleted_at | timestamptz | no | When soft-deleted (else NULL). |
| updated_at | timestamptz | no | Last config update. |

## Joins / lineage
- Aligns with `raw_fx.corridor_pricing` and `raw_fx.fx_rates` on send/receive currency.
- PII: none.
