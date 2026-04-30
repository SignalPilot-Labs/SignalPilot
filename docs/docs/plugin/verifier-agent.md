---
sidebar_position: 4
---

# Verifier Agent

The SignalPilot verifier agent is a 7-check post-build quality protocol that runs automatically after `dbt run` completes. It returns a structured receipt — not just pass/fail.

## When it runs

The verifier agent runs after the build step in the `dbt-workflow` skill lifecycle (Step 5: verify). It uses SignalPilot MCP tools to check the materialized model against expectations derived from the YML spec and source data.

## The 7 checks

| Check | What it verifies |
|-------|----------------|
| **Column alignment** | Materialized columns match YML-declared columns — no extra or missing columns. Uses `check_model_schema`. |
| **Row count validation** | Model is not empty, not obviously over-populated. Uses `validate_model_output`. |
| **Fan-out detection** | JOIN fan-out ratios within expected bounds — catches accidental cross joins. Uses `validate_model_output`. |
| **NULL scan** | Required columns (declared non-nullable in YML) have no unexpected NULLs. Uses `explore_columns`. |
| **Source row counts** | Upstream source tables have expected row counts — catches silent upstream failures. Uses `audit_model_sources`. |
| **Schema comparison** | No unintended column additions or removals vs. the previous run. Uses `schema_diff`. |
| **Grain analysis** | Cardinality per key matches the model's declared grain (e.g. one row per `order_id`). Uses `analyze_grain`. |

## Interpreting the output

The verifier returns a structured receipt:

```
Verifier receipt:
  duration:          12.3s
  agent turns:       4
  governed queries:  9
  queries blocked:   0
  models built:      1
  columns validated: 23

  Check results:
  ✓ column_alignment  — 23/23 columns match YML
  ✓ row_count         — 48,291 rows (expected: >0)
  ✓ fan_out           — max ratio 1.0x (threshold: 1.5x)
  ✓ null_scan         — 0 NULLs in required columns
  ✓ source_counts     — orders: 48,291 (stable)
  ✓ schema_diff       — no schema changes
  ✓ grain             — 1.00 rows per order_id (perfect grain)
```

A failed check includes the specific discrepancy:

```
  ✗ fan_out — ratio 3.2x on order_id (threshold: 1.5x)
              Probable cause: missing JOIN condition on date key
```

## What to do when a check fails

- **column_alignment** — a column in YML is missing from the SELECT or aliased incorrectly. Check the `dbt-write` skill.
- **row_count / empty model** — a filter is too aggressive, or an upstream source is empty. Use `audit_model_sources`.
- **fan_out** — a JOIN is missing a condition. Use `analyze_grain` to find the offending key.
- **null_scan** — a required column is NULL because the source is NULL or a COALESCE is missing.
- **source_counts** — run `audit_model_sources` to check upstream table health.
- **schema_diff** — a column was added or removed. Review the YML and regenerate with `generate_sql_skeleton` if needed.
- **grain** — use `analyze_grain` to identify which key has more than 1 row per value.
