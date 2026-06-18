# raw_openexchange.historical_rates

**Source system:** Open Exchange Rates API /historical/YYYY-MM-DD.json
**Grain:** one row per (rate_date, currency) — daily USD-base close
**Approx rows (demo scale):** ~3,090 days x 18 ccy ≈ 55k
**Loaded by:** warehouse/generators/gen_raw_openexchange.py

## Business definition
Daily USD-base closing rates per currency across NALA's full operating history,
mirroring the vendor's /historical endpoint. The long, thin time series used for
backtesting margins, reconciling treasury P&L, and charting corridor rates over
time. `rate` is units of `currency` per 1 USD.

## Known data-quality quirks
- One observation per day (the daily close), not intraday — coarser than `raw_fx.fx_rates`.
- At `NALA_SCALE=test` only every 7th day is emitted to keep the self-test tiny.
- `timestamp` is epoch SECONDS of that day's close (reserved word; double-quote it).
- `base` is always 'USD'.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK, dense counter. |
| rate_date | date | no | The historical day. |
| base | text | no | Always 'USD'. |
| currency | text | no | Quote currency code. |
| rate | numeric(24,10) | no | Units of `currency` per 1 USD at close. |
| timestamp | bigint | no | Epoch SECONDS of the close (reserved word; quote it). |
| ingested_at | timestamptz | no | When NALA ingested the day. |

## Joins / lineage
- `currency` -> `raw_openexchange.currencies.code`.
- Overlaps `raw_fx.fx_rates` (USD-base pairs) and informs `raw_fx.fx_pnl`.
- PII: none.
