# raw_fx.rate_providers

**Source system:** NALA internal fx-engine service (lookup config)
**Grain:** one row per upstream rate provider the engine can ingest from
**Approx rows (demo scale):** 6
**Loaded by:** warehouse/generators/gen_raw_fx.py

## Business definition
Lookup of the external rate sources the fx-engine blends to produce NALA's
internal mid rates (Open Exchange Rates, Reuters/Refinitiv, ECB, XE, plus the
internal blend pseudo-provider). `weight` is the provider's contribution to the
blended `INTERNAL_BLEND` rate. Used to attribute every `fx_rates` tick to where
it came from and to reason about provider reliability.

## Known data-quality quirks
- Contains a decommissioned provider (`BLOOMBERG`, `is_active=false`) kept for history.
- `INTERNAL_BLEND` is a synthetic provider (weight 1.0) representing the engine output, not an external feed.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| provider_id | integer | no | PK. Referenced by fx_rates.provider_id / snapshots.provider_id. |
| provider_code | text | no | Short code, e.g. OPENEXCHANGE, REUTERS, INTERNAL_BLEND. |
| provider_name | text | no | Human-readable provider name. |
| tier | text | no | primary / fallback / reference. |
| weight | numeric(5,4) | no | Blend weight in the internal rate engine. |
| is_active | boolean | no | False for decommissioned feeds. |
| created_at | timestamptz | no | When the provider was onboarded. |

## Joins / lineage
- `provider_id` is referenced by `raw_fx.fx_rates` and `raw_fx.fx_rate_snapshots` (not FK-enforced).
- `provider_code='OPENEXCHANGE'` corresponds conceptually to the `raw_openexchange` source.
