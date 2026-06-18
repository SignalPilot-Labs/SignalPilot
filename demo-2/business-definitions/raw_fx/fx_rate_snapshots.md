# raw_fx.fx_rate_snapshots

**Source system:** NALA internal fx-engine pricing cache
**Grain:** one row per board snapshot (USD-base rate board, every ~6h)
**Approx rows (demo scale):** ~12k
**Loaded by:** warehouse/generators/gen_raw_fx.py

## Business definition
A denormalized point-in-time cache of the entire USD-base rate board, written by
the pricing service on a coarse cadence. The full board of quote rates is stored
as a single `jsonb` map (`{"KES":129.1,"NGN":1551.2,...}`), which is how the
service hands the board to downstream consumers without N row lookups.

## Known data-quality quirks
- Rate board stored as a `jsonb` blob, not normalized rows — extract with `rates->>'KES'`.
- `source_label` free-text has legacy values (`legacy_cron`, `PRICING_CACHE_OLD`) alongside `fx-engine.v2`.
- Cadence is coarser (every ~6h) than fx_rates; do not expect a snapshot per tick.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| snapshot_id | bigint | no | PK. |
| snapshot_at | timestamptz | no | When the board was cached. |
| base_currency | text | no | Board pivot, always 'USD'. |
| rates | jsonb | no | Map of quote currency -> rate (quote per 1 USD). |
| provider_id | integer | no | -> rate_providers (not FK-enforced). |
| rate_count | integer | no | Number of currencies in the board. |
| source_label | text | no | Free-text origin label; has legacy values. |

## Joins / lineage
- `provider_id` -> `raw_fx.rate_providers.provider_id`.
- `rates` keys overlap `raw_openexchange.currencies.code`.
- PII: none.
