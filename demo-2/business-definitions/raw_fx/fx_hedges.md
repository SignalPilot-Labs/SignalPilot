# raw_fx.fx_hedges

**Source system:** NALA internal treasury hedging desk
**Grain:** one row per hedge position (spot / forward / swap)
**Approx rows (demo scale):** ~1,500
**Loaded by:** warehouse/generators/gen_raw_fx.py

## Business definition
Treasury hedge positions used to manage NALA's FX exposure across corridors —
spots, forwards, and swaps booked with bank counterparties (MUFG, Citi, StoneX,
etc.). Supports the stablecoin/pre-funding strategy (e.g. the MUFG-backed credit
line) by locking rates ahead of settlement.

## Known data-quality quirks
- `value_date` < EPOCH_END implies the hedge is `settled`; future value_date implies `open`. ~4% `cancelled` regardless.
- `mark_to_market_usd` can be negative.
- Spots settle T+2; forwards/swaps at 30/60/90/180 days.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| hedge_id | text | no | PK, UUID via det_uuid(("fx_hedge", i)). |
| instrument | text | no | spot / forward / swap. |
| base_currency | text | no | Base (always USD here). |
| quote_currency | text | no | Quote currency being hedged. |
| notional | numeric(24,2) | no | Notional amount. |
| notional_ccy | text | no | Currency of notional (USD). |
| strike_rate | numeric(20,8) | no | Contracted rate. |
| counterparty | text | no | Bank counterparty name. |
| trade_date | date | no | Trade booking date. |
| value_date | date | no | Settlement date. |
| status | text | no | open / settled / cancelled. |
| mark_to_market_usd | numeric(20,2) | no | Current MtM in USD (can be negative). |
| created_at | timestamptz | no | Booking timestamp. |
| updated_at | timestamptz | no | Last update / settlement timestamp. |

## Joins / lineage
- Pairs align with `raw_fx.fx_pnl` / `raw_fx.fx_rates` on base/quote currency.
- PII: none (counterparties are institutions, not persons).
