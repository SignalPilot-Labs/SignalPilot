# raw_compliance.risk_scores

**Source system:** internal NALA compliance operations (MLRO / compliance team source of record)
**Grain:** one row per customer risk-score snapshot (re-scored periodically and on events)
**Approx rows (demo scale):** ~84,000 (one per customer, plus a re-score history of 2-3 on ~25%)
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
A point-in-time composite risk score for a NALA customer, produced by the internal customer-risk-scoring model. Each snapshot carries the 0..100 `score`, the `risk_band`, the model version, the factor-contribution blob, and the PEP/sanctions/adverse-media/high-risk-country flags that feed downstream case creation. `is_current` is meant to flag the latest score per customer but is deliberately messy.

## Known data-quality quirks
- `is_current` SCD flag is buggy: occasionally more than one row per customer is marked current (~4% extra-current).
- `risk_band` distribution: ~62% low, ~28% medium, ~8.5% high, ~1.5% prohibited.
- `pep_flag` ~3%, `adverse_media_flag` ~5%, `high_risk_country` ~20%; `sanctions_flag` only on ~half of prohibited rows.
- This is OUR system, so `scored_at`/`created_at` are clean tz-aware `timestamptz` (no string drift).
- `factors` is a jsonb contribution blob.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK |
| customer_code | text | no | CUS_... (join key) |
| customer_uuid | uuid | no | canonical customer uuid (alt join key) |
| score | integer | no | 0..100 composite risk score |
| risk_band | text | no | low / medium / high / prohibited |
| model_version | text | no | e.g. crs-v2.3 |
| factors | jsonb | no | factor-contribution blob (geography, pep, velocity, ...) |
| pep_flag | boolean | no | PEP flag (~3%) |
| sanctions_flag | boolean | no | sanctions flag |
| adverse_media_flag | boolean | no | adverse-media flag (~5%) |
| high_risk_country | boolean | no | high-risk-country flag (~20%) |
| is_current | boolean | no | latest-score flag (messy SCD; sometimes >1 current) |
| scored_at | timestamptz | no | when the score was produced (tz-aware) |
| created_at | timestamptz | no | row insert time (tz-aware) |

## Joins / lineage
- `customer_code` / `customer_uuid` -> customer_master.
