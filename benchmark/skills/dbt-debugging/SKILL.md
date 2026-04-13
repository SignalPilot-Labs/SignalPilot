---
name: dbt-debugging
description: "Use this skill when dbt run fails with any error, when a model builds but produces wrong values, or when row counts don't match expectations. Covers: dbt compile failure protocol (isolate with --select, ref-not-found ephemeral stub fix, Jinja errors), DuckDB-specific error messages with exact fixes, iterative fix strategy, zero-row model diagnosis, fan-out playbook (pre-aggregate, ROW_NUMBER dedup), over-filter playbook (binary search conditions, INNER vs LEFT JOIN), value mismatch playbook (currency scale, date format), and how to use dbt_error_parser MCP tool."
type: skill
---

# Debugging Skill

## 1. Use dbt_error_parser First

```
mcp__signalpilot__dbt_error_parser(error_text="<paste full dbt error output>")
```

Run this immediately when dbt fails — it returns structured fix suggestions.

## 2. Compile Failure Protocol

- Isolate: `dbt run --select <failing_model>` — do not re-run all models each attempt
- Ref not found: check `.sql` filename matches `ref()` call exactly. If missing, create ephemeral stub:
  ```sql
  {{ config(materialized='ephemeral') }}
  select * from main.raw_table
  ```
- Jinja error: unclosed `{{ }}`, wrong macro name, undefined variable
- Never run `dbt deps` unless `packages.yml` exists — it wipes pre-installed packages
- After fixing: `dbt run --select <model>+` to rebuild model and all dependents

## 3. Database Error Protocol — DuckDB-Specific Messages

- `invalid date field format` → `STRPTIME(col, '%d/%m/%Y')::DATE`
- `Table ... does not exist` → `explore_table` to check actual table names
- `column ... not found` → `describe_table` for exact names
- `No function matches ... DOUBLE / VARCHAR` → add explicit `CAST()`
- `Could not convert string ... to INT64` → use `TRY_CAST(col AS INTEGER)`
- `Cannot mix values of type TIMESTAMP and INTEGER in COALESCE` → cast both args to same type
- `fivetran_utils is undefined` → run `dbt deps` first (only if `packages.yml` exists)

## 4. Zero-Row Model Diagnosis

Model compiles but `SELECT COUNT(*) FROM model` returns 0:
- Check source table is not empty
- Check upstream `ref()` model is not empty
- Binary search: remove WHERE/JOIN conditions one at a time, count rows each time

## 5. Fan-Out Playbook

Diagnose:
```sql
SELECT join_key, COUNT(*) AS cnt FROM model GROUP BY join_key HAVING cnt > 1 ORDER BY cnt DESC LIMIT 10
```

Fix A — pre-aggregate right table before joining:
```sql
WITH deduped AS (
  SELECT join_col, MAX(value) AS value FROM right_table GROUP BY join_col
)
SELECT l.*, d.value FROM left_table l
INNER JOIN deduped d ON l.join_col = d.join_col
```

Fix B — `SELECT DISTINCT` (only when all output columns are determinate and fact table rules don't apply)

Fix C — ROW_NUMBER dedup:
```sql
ROW_NUMBER() OVER (PARTITION BY join_key ORDER BY updated_at DESC) AS rn
-- then WHERE rn = 1
```

## 6. Over-Filter Playbook

Binary search:
```sql
SELECT COUNT(*) FROM source_table WHERE cond_1;            -- still same? keep
SELECT COUNT(*) FROM source_table WHERE cond_1 AND cond_2; -- drops? cond_2 is culprit
```

Check INNER JOIN vs LEFT JOIN:
```sql
SELECT COUNT(*) FROM left_table l
LEFT JOIN right_table r ON l.id = r.id
WHERE r.id IS NULL;
-- If count > 0 and those rows should appear: switch to LEFT JOIN
```

`LEFT JOIN + WHERE right.col IS NOT NULL` = silent INNER JOIN anti-pattern.

## 7. Value Mismatch Playbook

- Currency scale: `SELECT MIN(amount), MAX(amount) FROM table` — values of 150000 when expecting 1500.00 = cents vs dollars
- Date format: always `explore_table` before assuming format
- Validate formula on 2-3 known rows manually before writing SQL

## 8. Reading dbt Output Efficiently

- Scan for lines containing `ERROR` or `FAIL` only
- Final summary: `Completed with N errors and N warnings`
- Model name before each ERROR is the file to fix
- Skip: INFO lines about compilation, elapsed time, adapter info
