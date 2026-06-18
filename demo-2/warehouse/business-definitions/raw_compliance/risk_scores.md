# raw_compliance.risk_scores

**Source system:** NALA internal compliance system (customer risk model)
**Grain:** one row per customer risk score snapshot
**Approx rows (demo scale):** ~80k (1 per customer + periodic re-scores)
**Loaded by:** warehouse/generators/gen_raw_compliance.py

## Business definition
Periodic + event-driven composite risk score (0-100) per customer, banded
low/medium/high/prohibited, with the contributing factors. Drives EDD, monitoring
frequency, and case auto-opening thresholds.

## Known data-quality quirks
- SCD-ish: is_current flags the latest score, but a ~4% bug means a customer can
  occasionally have MORE THAN ONE row marked current - dedupe by latest scored_at.
- model_version spans crs-v1.0 .. crs-v3.0 (scores not directly comparable across).
- Internal system: timestamps are clean timestamptz.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK |
| customer_code | text | no | CUS_00000123 (join key) |
| customer_uuid | uuid | no | canonical customer uuid |
| score | integer | no | 0..100 composite risk score |
| risk_band | text | no | low / medium / high / prohibited |
| model_version | text | no | scoring model version |
| factors | jsonb | no | per-factor contribution blob |
| pep_flag | boolean | no | politically-exposed-person flag |
| sanctions_flag | boolean | no | sanctions-match flag |
| adverse_media_flag | boolean | no | adverse-media flag |
| high_risk_country | boolean | no | high-risk geography flag |
| is_current | boolean | no | latest score? (messy: occasionally >1 true) |
| scored_at | timestamptz | no | when scored |
| created_at | timestamptz | no | row creation |

## Joins / lineage
- Joins to NALA core customers on customer_code (or customer_uuid).
- Dedupe to current score by latest scored_at per customer_code (row_number window).
