# raw_fx.fx_rates

**Source system:** NALA internal fx-engine service (rate ingestion)
**Grain:** one row per (currency pair, timestamp tick) — hourly at demo scale
**Approx rows (demo scale):** ~3.48M (capped, see quirks)
**Loaded by:** warehouse/generators/gen_raw_fx.py

## Business definition
The fx-engine's mid/bid/ask time series for every currency pair NALA prices:
each SEND currency (GBP/USD/EUR) against every receive-market currency, USD
against all receive currencies (the treasury board), the send-side majors
(GBP/USD, EUR/USD, GBP/EUR), and USD against each stablecoin (peg monitoring).
Rates are anchored on the indicative `common.USD_FX` levels with deterministic
daily + intraday drift. This is the canonical rate source the pricing and quote
services consume.

## Known data-quality quirks
- **Row cap:** fully hourly across 2018-01-01..2026-06-18 (~74k hours) x 47 pairs would
  be ~3.48M rows. A hard cap of `MAX_FX_ROWS = 4_500_000` is enforced in the
  generator; if pairs x hours ever exceeded it, the tick cadence (`cadence_hours`)
  is widened automatically. At current demo scale cadence stays hourly (1h). At
  `NALA_SCALE=test` cadence is forced to one tick/day.
- Timestamp stored THREE ways: `ts_iso` (ISO-Z text string), `ts_epoch_ms`
  (legacy epoch-ms bigint), `ingested_at` (real timestamptz). All encode the same instant.
- ~1.5% of ticks flagged `is_stale=true` (provider feed lag).
- `provider_id` is dominated by the `INTERNAL_BLEND` provider (id 5).
- Exotic-currency spreads are wide (15-70 half-bps); majors and stablecoins tight.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| rate_id | bigint | no | PK, dense counter. |
| base_currency | text | no | Base of the pair, e.g. GBP. |
| quote_currency | text | no | Quote of the pair, e.g. KES. units of quote per 1 base. |
| pair | text | no | Denormalized 'BASE/QUOTE' convenience string. |
| mid_rate | numeric(20,8) | no | Mid rate (quote per base). |
| bid_rate | numeric(20,8) | no | Bid; always <= mid. |
| ask_rate | numeric(20,8) | no | Ask; always >= mid. |
| spread_bps | numeric(10,4) | no | (ask-bid)/mid in basis points. |
| provider_id | integer | no | -> rate_providers (not FK-enforced). |
| ts_iso | text | no | ISO-Z string of the tick instant. |
| ts_epoch_ms | bigint | no | Legacy epoch-ms of the same instant. |
| ingested_at | timestamptz | no | Clean tz-aware timestamp of the tick. |
| is_stale | boolean | no | Engine flagged the tick as stale. |

## Joins / lineage
- `provider_id` -> `raw_fx.rate_providers.provider_id`.
- Pairs align with `raw_fx.corridor_pricing` / `pricing_margins` on send/receive currency.
- Conceptually overlaps `raw_openexchange.historical_rates` (USD-base daily close).
- PII: none — FX market data carries no personal data.
