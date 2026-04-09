---
name: dbt-verification
description: "Use this skill after dbt build succeeds on any priority model, and again before declaring the task complete. Contains exact MCP tool call syntax for check_model_schema (missing column detection), validate_model_output (row count and fan-out), analyze_grain (cardinality check), plus a zero-row guard, sample inspection checklist for silent wrong-answer patterns (all-NULL column, 1970 dates, identical values, wrong join key), and output table name verification. FAILURE TO RUN THESE CHECKS = GUARANTEED SCORE OF ZERO."
type: skill
---

# Verification Skill

## Run Immediately After Every Successful dbt build — For Each Priority Model

### Step 1 — Zero-Row Guard

```
mcp__signalpilot__validate_model_output(connection_name="<id>", model_name="<model>")
```

If 0 rows returned: stop, debug JOIN/WHERE before continuing. Do not proceed.

### Step 2 — Column Schema Check

```
mcp__signalpilot__check_model_schema(
  connection_name="<id>",
  model_name="<model>",
  yml_columns="col1, col2, col3"
)
```

Paste the exact comma-separated column names from the model's YML `columns:` list.
If MISSING columns reported: add them to SQL, re-run dbt. Do NOT finish until all columns match.

### Step 3 — Fan-Out Check

`validate_model_output` also detects fan-out. If fan-out detected: pre-aggregate the right-side table before joining, or use `ROW_NUMBER()` dedup.

### Step 3b — Full Source Cardinality Audit (replaces manual fan-out checks)

Run this ONCE after every successful build, passing ALL tables you joined:
```
mcp__signalpilot__audit_model_sources(
  connection_name="<id>",
  model_name="<model>",
  source_tables="table_a, table_b, table_c"
)
```

Interpreting results:
- **FAN-OUT (ratio > 2x)**: The model output is larger than a source. Pre-aggregate that source before joining, or add a deduplication step with ROW_NUMBER().
- **OVER-FILTER (ratio < 0.5)**: The model output is less than half of a source. Change INNER JOIN to LEFT JOIN, or identify and remove the over-restrictive WHERE clause.
- **CONSTANT column**: Every output row has the same value. Run `SELECT DISTINCT <col> FROM <source_table>` — your CASE WHEN literal likely doesn't match any source value.
- **50%+ NULL column**: A LEFT JOIN is silently dropping most values. Verify the join key column name is correct on both sides.

### Step 4 — Grain / Cardinality Check

```
mcp__signalpilot__analyze_grain(connection_name="<id>", model_name="<model>")
```

Unexpected duplicates = fix before finishing.

### Step 5 — Sample Inspection

```
mcp__signalpilot__query_database(connection_name="<id>", sql="SELECT * FROM <model> LIMIT 5")
```

Silent failure patterns to check:
- Numeric column is 0 or NULL for every row → aggregation or JOIN logic is wrong
- Date column shows 1970 or far-future dates → date format mismatch (use STRPTIME)
- String column echoes the join key instead of a label → wrong column in SELECT
- Any column identical for all 5 rows when it should vary → CASE WHEN literal typo
- Spot check: if task description references a known entity, query `WHERE <known_condition>` and verify it is present

### Step 6 — Output Table Name Verification

```
mcp__signalpilot__query_database(connection_name="<id>", sql="SHOW TABLES")
```

Every eval-critical model name must appear exactly as written. If missing:
1. Check `.sql` filename matches model name character-for-character
2. Check `dbt_project.yml` for alias or schema overrides
3. Create a passthrough: `SELECT * FROM {{ ref('your_existing_model') }}` in a new file with the correct name
4. Run `dbt run --select <model>`

## 5-Step Row Count Audit

For manual diagnosis when validate_model_output flags issues:

- **Step A**: `SELECT COUNT(*) AS source_rows, COUNT(DISTINCT <pk>) AS unique_pks FROM <source>`
- **Step B**: `SELECT COUNT(*) AS output_rows FROM <model>`
- **Step C**: decide correctness — aggregation model: `output_rows == COUNT(DISTINCT group_key)`; pass-through: `output_rows <= source_rows`
- **Step D**: fan-out — `SELECT <join_key>, COUNT(*) FROM <model> GROUP BY 1 HAVING COUNT(*) > 1`
- **Step E**: over-filter — remove one WHERE/JOIN condition at a time, counting rows each time; check if INNER JOIN should be LEFT JOIN
