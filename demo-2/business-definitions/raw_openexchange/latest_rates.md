# raw_openexchange.latest_rates

**Source system:** Open Exchange Rates API /latest.json
**Grain:** one row per (fetch, currency); fetches every ~6h over the last ~120 days
**Approx rows (demo scale):** ~120 days x 4/day x 18 ccy ≈ 8.6k
**Loaded by:** warehouse/generators/gen_raw_openexchange.py

## Business definition
The vendor's most-recent USD-base rate map, polled periodically by the fx-engine.
`rate` is units of `currency` per 1 USD (base always 'USD' on the free plan).
Only a recent rolling window is retained (the vendor only serves "latest").

## Known data-quality quirks
- Only the last ~120 days of fetches are kept — this is NOT a full history (use `historical_rates` for that).
- `timestamp` is the vendor's epoch-SECONDS field (note the reserved-word column name; double-quote it).
- `disclaimer` is mostly NULL — the vendor only populates it ~5% of the time.
- `base` is always 'USD'.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK, dense counter. |
| base | text | no | Always 'USD'. |
| currency | text | no | Quote currency code. |
| rate | numeric(24,10) | no | Units of `currency` per 1 USD. |
| timestamp | bigint | no | Epoch SECONDS of the vendor tick (reserved word; quote it). |
| fetched_at | timestamptz | no | When the engine fetched it. |
| disclaimer | text | no | Vendor boilerplate, usually NULL. |

## Joins / lineage
- `currency` -> `raw_openexchange.currencies.code`.
- Conceptually the source feed for `raw_fx.fx_rates` provider 1 (OPENEXCHANGE).
- PII: none.
