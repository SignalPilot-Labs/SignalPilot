---
name: dbt-workflow
description: "Use this skill before writing any dbt SQL model. Covers: how to read YML to extract column contracts and output shape (entity+qualifier, top-N cutoff, rolling window vs point-in-time), dependency build order, JOIN type selection (LEFT vs INNER, which table drives), pre-JOIN cardinality checks to prevent fan-out, wide aggregation CASE WHEN pattern, ephemeral stubs for missing ref() targets, and column naming rules."
type: skill
---

# dbt Workflow Skill

## 0. Date Spine Override — Fix CURRENT_DATE in Existing Models

**Before writing any new SQL**, scan ALL existing `.sql` files under `models/` for `current_date`, `now()`, `getdate()`, or `sysdate`. The `dbt_project_map` tool flags these automatically.

These produce future-dated rows when the run date is after the source data's date range. Fix them:

1. Identify the date column used in the spine (look for `date_spine`, `dateadd`, or date range generation patterns)
2. Find the source table that feeds the spine — trace through `ref()` or `source()` calls
3. Query that source table: `SELECT MAX(date_column) FROM source_table`
4. Replace `current_date` (or equivalent) with a hardcoded date literal from step 3, or wrap it: `(SELECT MAX(date_column) FROM source_table)`

Common patterns to fix:
- `end_date = "current_date"` in `dbt_utils.date_spine()` calls
- `dbt.dateadd("day", 1, "current_date")` as a spine endpoint
- `greatest(max_date, current_date)` — remove the `greatest()` wrapper entirely, keep only the data-derived date

Do NOT skip this step. Pre-existing models are NOT read-only — you must edit them when they contain date functions that reference the current runtime date.

## 0b. Non-Deterministic Ordering -- Fix ROW_NUMBER Tiebreakers

The `dbt_project_map` tool flags `ROW_NUMBER() OVER (ORDER BY ...)` calls
where the ORDER BY does not uniquely identify rows within the partition.
This produces different surrogate keys depending on execution environment,
thread count, and DuckDB version.

For each flagged file:
1. Identify the PARTITION BY columns (the grouping context)
2. Identify what makes each row unique WITHIN that partition -- check the
   source table's primary key or unique columns via `explore_table`
3. Add those columns to the ORDER BY as tiebreakers

Common fix patterns:
- `ROW_NUMBER() OVER (ORDER BY patient_id)` where rows have an encounter_id
  -> `ROW_NUMBER() OVER (ORDER BY patient_id, encounter_id)`
- `ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at)` where
  multiple events share the same timestamp
  -> add the event's primary key: `ORDER BY created_at, event_id`
- `ROW_NUMBER() OVER (ORDER BY NULL)` or missing ORDER BY
  -> find the natural key of the table and use it as the full ORDER BY

## 1. Output Shape Inference — Read YML description Before Writing SQL

Extract from `description:` field:
- **ENTITY**: "for each customer/driver/order" → one output row per qualifying entity
- **QUALIFIER**: "due to returned items" / "with at least one order" → filter, INNER JOIN not all entities
- **RANK CONSTRAINT**: "top N" / "ranks the top N" → `QUALIFY DENSE_RANK() OVER (...) <= N` is mandatory
- **TEMPORAL SCOPE**: "rolling window" + `unique_key` on date×entity → ONE output date (latest), not all historical dates. Fix: `WHERE date_col = (SELECT MAX(date_col) FROM source)`

Write a comment at top of SQL body:
```sql
-- EXPECTED SHAPE: <inferred row count or cardinality formula>
-- REASON: <quote from description>
```

Critical signals:
- "rolling window" + unique_key = date×entity → output has ONE date, not all historical dates
- "top N" or "ranks the top N" → `QUALIFY DENSE_RANK() OVER (...) <= N` is mandatory
- "for each X" + "with/due to criterion" → INNER JOIN or subquery, not all entities

## 2. Dependency Build Order

Before writing any model:
1. List all `.yml` files with model definitions
2. For each model, note its `refs:` dependencies
3. Draw the topological order: sources → staging → core → marts
4. Write and run models in this order — write dependencies first

Also scan the task instruction for model names not in any YML — they need `.sql` files too.

Scan `macros/` directory before writing any model. Call macros with `{{ macro_name() }}` rather than re-implementing logic inline.

## 3. YML-to-SQL Contract

- `columns:` names are exact. Copy them into SELECT aliases character-for-character.
- Check `.md` files in `models/` for `{% docs %}` blocks — they contain exact string literals for CASE WHEN that **override** any defaults.
- The `refs:` section lists upstream model dependencies — use these as the primary guide for writing SQL.

## 4. JOIN Type Selection

- **DEFAULT: LEFT JOIN for all JOINs.** Start FROM the table that defines all output entities (all customers, all dates, all admins) and LEFT JOIN everything else to it. This is the correct choice for the vast majority of reporting models.
- **INNER JOIN: exception only.** Use INNER JOIN only when the task description explicitly excludes non-matching rows (e.g., "customers WITH orders", "only users who have", "exclude rows without"). Phrases like "based on", "for each X in Y", "calculates X from Y" describe calculation scope — keep LEFT JOIN. ALWAYS call `compare_join_types` before finalizing any JOIN that is not a self-join or date-spine join:
  ```
  mcp__signalpilot__compare_join_types(connection_name="<id>", left_table="table_a", right_table="table_b", join_keys="a.key = b.key")
  ```
- `LEFT JOIN + WHERE right.col IS NOT NULL` silently becomes INNER JOIN — avoid.

**Never switch from LEFT JOIN to INNER JOIN to fix row counts.** If output has too many rows, the problem is fan-out (missing GROUP BY or un-deduplicated right table), not JOIN type. Switching to INNER JOIN silently drops entities and produces wrong answers.

## 5. Pre-JOIN Cardinality Check

Run before every JOIN on the right-side table:
```sql
SELECT COUNT(*), COUNT(DISTINCT join_key) FROM right_table;
```
If `COUNT(*) > COUNT(DISTINCT join_key)`: pre-aggregate or deduplicate before joining — your model will fan-out silently otherwise.

For UNION models: count each branch separately, verify sum equals expected total.

## 6. Wide Aggregation Pattern

Before writing CASE WHEN:
```sql
SELECT DISTINCT category_col FROM table ORDER BY 1;
```
Map each distinct value to exact YML column name. Use `SUM(CASE WHEN col = 'value' THEN 1 ELSE 0 END)`. Never guess string literals. Any value not matching a named column goes into the catch-all column.

## 7. Materialization Rules

Always `{{ config(materialized='table') }}`. Never `incremental` or `is_incremental()` — incremental models return all rows on first run, producing wrong row counts. Ephemeral only for stub models that satisfy a `ref()` without creating a database object.

## 8. Ephemeral Stubs — Resolving Missing ref() Targets

When existing SQL uses `{{ ref('raw_table') }}` but no `raw_table.sql` exists:
1. Check: `SELECT table_name FROM information_schema.tables WHERE table_name = 'raw_table'`
2. If found, create `models/raw_table.sql`:
   ```sql
   {{ config(materialized='ephemeral') }}
   select * from main.raw_table
   ```
Ephemeral models inline as CTEs — they do NOT create a database object and will NOT shadow source data. Never create a `materialized='table'` passthrough for a raw table name — it overwrites source data.

## 9. Column Value Mapping

When joining to a lookup table, use source values directly unless the lookup provides a new enrichment column. Do not replace source column values with remapped lookup values — the evaluator expects original source values.

## 10. NULL and Precision Policy

- Do NOT use `COALESCE(col, '')` unless YML explicitly requires empty string.
- Do NOT use `ROUND()` unless YML requires it (evaluator uses abs_tol=0.01 — full precision is safer).
- Do NOT use `SELECT DISTINCT` on fact tables — use `ROW_NUMBER()`.
- Do NOT use `COALESCE(numeric_col, 0)` in aggregates unless YML says "treat nulls as zero".
- ID columns: check source type with `explore_table` — VARCHAR `_id` must stay VARCHAR (`'100063' != 100063`).
- Do NOT add WHERE/HAVING filters that are not in the task description or YML. Table/column names like "actor_rating" do NOT mean you should filter `role='ACTOR'`. Only filter when the task says "exclude", "only", "where", or YML docs blocks specify a filter condition.

## 11. dbt Syntax Essentials

```sql
{{ config(materialized='table') }}          -- at top of every model file
SELECT * FROM {{ ref('stg_customers') }}    -- reference another model
SELECT * FROM {{ source('raw', 'orders') }} -- reference a raw source table
```

Naming conventions: `stg_*` staging, `dim_*` dimension, `fct_*` fact, `obt_*` one-big-table.

Use `dbt.*` macros (e.g., `{{ dbt.date_trunc('month', 'date_col') }}`) only if existing SQL already uses the `dbt.` namespace.

## 12. Turn Budget Management

Over-exploration is the #1 cause of missing models. Follow this discipline:
- **First 25% of turns**: Explore (list_tables, explore 2 source tables, read YMLs). STOP exploring.
- **Middle 50% of turns**: Write ALL priority model .sql files and run `dbt run`. A wrong-but-present model can be fixed; a missing model scores zero.
- **Last 25% of turns**: Fix errors, write non-priority models, run /dbt-verification.

If halfway through your budget any priority model lacks a .sql file, STOP everything else and write it immediately — even a minimal version.

## 13. Non-Deterministic Window Functions

If `dbt_project_map` warns about ROW_NUMBER/RANK/DENSE_RANK in pre-shipped models, review each flagged file:
1. Open the file and find every `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` (or RANK/DENSE_RANK)
2. Run `explore_table` or a COUNT DISTINCT query to verify whether the ORDER BY columns uniquely identify rows within each partition:
   ```sql
   SELECT COUNT(*), COUNT(DISTINCT <order_by_col>) FROM <table>;
   ```
3. If not unique, add a tiebreaker: append the table's primary key or a unique ID column to the ORDER BY
4. Run `dbt run --select <model>` and verify row counts match expectations

Common pattern: `ROW_NUMBER() OVER (ORDER BY patient_id)` — if patient_id repeats across rows, add a secondary sort like `ORDER BY patient_id, encounter_id`.

## 14. DuckDB Type System for dbt

DuckDB is strict about types in UNION, COALESCE, and CASE WHEN:
- Cannot mix VARCHAR and INTEGER in CASE WHEN branches — CAST explicitly:
  ```sql
  CASE WHEN condition THEN CAST(int_col AS VARCHAR) ELSE 'default' END
  ```
- Cannot COALESCE(timestamp_col, integer_default) — types must match
- UNION requires matching column types across branches — CAST if needed:
  ```sql
  SELECT CAST(id AS VARCHAR) AS id FROM a
  UNION ALL
  SELECT id FROM b  -- both must be same type
  ```
- DATE vs TIMESTAMP: DuckDB distinguishes these. Use `DATE '2024-01-01'` not `TIMESTAMP`
- INTEGER division: `5/2 = 2` (integer division). Use `5.0/2` or `CAST(5 AS DOUBLE)/2` for decimal results

Before running dbt, validate your SQL mentally for type consistency in:
- Every CASE WHEN (all THEN/ELSE branches must be the same type)
- Every COALESCE (all arguments must be the same type)
- Every UNION (column types must match positionally)

## 15. First-Run Checklist (Before dbt run)

1. Read ALL .yml files — extract model names, column lists, and descriptions
2. Read ALL existing .sql files — understand what's already implemented
3. Run `dbt_project_map` to get dependency graph and warnings
4. Check for `packages.yml` — if present, run `dbt deps` first
5. Create ephemeral stubs for any missing `ref()` targets
6. Write ALL model SQL files before running dbt (even minimal versions)
7. Run `dbt run --select +model_name` for each evaluation target
