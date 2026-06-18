# raw_fx.fx_pnl

**Source system:** NALA internal treasury / fx-engine P&L
**Grain:** one row per (currency pair, P&L date) — weekly marks at demo scale
**Approx rows (demo scale):** ~6.6k
**Loaded by:** warehouse/generators/gen_raw_fx.py

## Business definition
Treasury's realized and unrealized FX P&L per currency pair. Captures the
trading margin NALA earns moving money across corridors plus mark-to-market on
open positions. Volume scales up across the epoch to mirror business growth.

## Known data-quality quirks
- Marked weekly (Mondays), not daily, to keep the table demo-sized.
- Covers a treasury subset of pairs (USD vs each receive currency, plus GBP/USD, EUR/USD) — not every fx_rates pair.
- `unrealized_pnl_usd` can be negative (open-position mark).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| pnl_id | bigint | no | PK. |
| pnl_date | date | no | The P&L mark date. |
| base_currency | text | no | Base of the pair. |
| quote_currency | text | no | Quote of the pair. |
| volume_usd | numeric(20,2) | no | Traded volume in USD that period. |
| realized_pnl_usd | numeric(20,2) | no | Realized FX P&L in USD. |
| unrealized_pnl_usd | numeric(20,2) | no | Mark-to-market on open positions (can be negative). |
| avg_margin_bps | numeric(10,4) | no | Average realized margin in bps. |
| notional_local | numeric(24,2) | no | Notional in the quote currency. |
| notional_ccy | text | no | Currency of notional_local. |
| created_at | timestamptz | no | When the mark was written. |

## Joins / lineage
- Pairs align with `raw_fx.fx_rates` and `raw_fx.fx_hedges` on base/quote currency.
- PII: none.
