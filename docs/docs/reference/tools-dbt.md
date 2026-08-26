---
sidebar_position: 4
---

# dbt Tools

8 tools for dbt intelligence and model verification.

---

## dbt Intelligence

### generate_sql_skeleton

Generate a SQL template from a YML column spec and referenced tables.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `project` | string | Yes | dbt project name |
| `model` | string | Yes | Model name to generate skeleton for |

**Returns:** SQL template with CTEs for each declared column in the YML. Column aliases are pre-populated to match YML exactly (case-sensitive).

**When to use:** Step 4 of the dbt-workflow skill — get the initial SQL structure before filling in logic.

---

### dbt_error_parser

Parse raw dbt error output into structured diagnosis and fix suggestion.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `error_text` | string | Yes | Raw text from `dbt run` or `dbt parse` stderr |
| `project` | string | No | dbt project name for context |

**Returns:** Error type (e.g. `duplicate_patch`, `ref_not_found`, `compilation_error`), affected model, structured fix suggestion.

**Error types handled:**
- `duplicate_patch` — same model patched in multiple YML files
- `ref_not_found` — `ref()` to a non-existent model
- `compilation_error` — SQL syntax error in a model file
- `passthrough_warning` — model returns all columns (`SELECT *`)
- `current_date_hazard` — `current_date`/`now()` in a date-spine model
- `zero_rows` — model builds but returns 0 rows

---

### analyze_grain

Cardinality analysis: per-key distinct counts and fan-out factors.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `table` | string | Yes | Table to analyze (usually a freshly built dbt model) |
| `grain_keys` | array | Yes | Columns that define the expected grain |

**Returns:** Per-key distinct count, rows per key (mean/max), fan-out factor. Fan-out > 1.0 means the grain is violated.

**When to use:** When verifying that a model has the expected grain (e.g. one row per `order_id`).

---

### compare_join_types

Compare row counts across INNER, LEFT, RIGHT, and FULL OUTER JOIN for a given join condition.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `left_table` | string | Yes | Left table |
| `right_table` | string | Yes | Right table |
| `join_on` | string | Yes | Join condition (e.g. `order_id`) |

**Returns:** Row count per join type, NULL counts on each side — helps pick the right join before writing a model.

---

## Model Verification

### check_model_schema

Compare materialized columns against YML-declared columns.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `project` | string | Yes | dbt project name |
| `model` | string | Yes | Model name |

**Returns:** Column alignment: columns present in DB but not in YML (extra), columns in YML but not in DB (missing), type mismatches.

**When to use:** After `dbt run` — verify the materialized table matches the YML contract.

---

### validate_model_output

Row count validation, fan-out detection, and empty model detection.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `table` | string | Yes | Materialized table to validate |
| `expected_min_rows` | integer | No | Minimum expected row count (default: 1) |
| `fan_out_threshold` | number | No | Max acceptable fan-out ratio (default: 1.5) |

**Returns:** Row count, empty model flag, fan-out ratio per key column, pass/fail per check.

---

### verify_model_values

Cross-validate a model's aggregate metric values against raw source data. Queries the model output, identifies numeric (metric) columns and the largest dimension slice, then independently runs `COUNT(*)` and `COUNT(DISTINCT <key>)` on each upstream table for that slice.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection_name` | string | Yes | Connection name |
| `model_name` | string | Yes | dbt model / table to verify |

**Returns:** Value verification report — model values vs source baselines, flagging any discrepancy.

**When to use:** After building a model, to catch wrong aggregation functions (e.g. `COUNT(DISTINCT id)` where `COUNT(*)` is correct).

---

### audit_model_sources

Upstream audit: source row counts, fan-out/over-filter ratios, and NULL scan.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection` | string | Yes | Connection name |
| `project` | string | Yes | dbt project name |
| `model` | string | Yes | Model to audit sources for |

**Returns:** Per-source table: row count, fan-out ratio (rows in model / rows in source), over-filter ratio, NULL count on key columns.

**When to use:** When `validate_model_output` shows unexpected row counts — trace back to which source is responsible.
