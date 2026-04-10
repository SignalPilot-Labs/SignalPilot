---
name: dbt-workflow
description: "Use this skill before writing any dbt SQL model. Covers: how to read YML to extract column contracts and output shape (entity+qualifier, top-N cutoff, rolling window vs point-in-time), dependency build order, JOIN type selection (LEFT vs INNER, which table drives), pre-JOIN cardinality checks to prevent fan-out, wide aggregation CASE WHEN pattern, ephemeral stubs for missing ref() targets, and column naming rules."
type: skill
---

# dbt Workflow Skill

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
- **INNER JOIN: exception only.** Use INNER JOIN only when the task description explicitly excludes non-matching rows (e.g., "customers WITH orders", "drivers who completed a trip"). When considering INNER JOIN, call `compare_join_types` first to confirm row counts match expectations:
  ```
  mcp__signalpilot__compare_join_types(connection_name="<id>", left_table="table_a", right_table="table_b", join_keys="a.key = b.key")
  ```
- `LEFT JOIN + WHERE right.col IS NOT NULL` silently becomes INNER JOIN — avoid.

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
