---
name: dbt_expert
description: "Core dbt knowledge for Spider2-DBT benchmark tasks — project structure, YAML-to-SQL workflow, common patterns, and DuckDB-specific syntax."
type: skill
applicable_dbs: ["duckdb"]
priority: 10
---

# dbt Expert Skill

## Task Pattern
Spider2-DBT tasks give you an **unfinished dbt project**. Your job:
1. Read `.yml` files to find model definitions
2. Identify which `.yml` files have NO corresponding `.sql` file — those are the models you must create
3. Write the SQL, run `dbt run`, fix errors, repeat

## Model Discovery — Beyond YAML

Not all required models are listed in `.yml` files. Before writing SQL, run two discovery passes:

1. **YAML scan** — find every model in `models:` blocks with no matching .sql file (standard)
2. **Instruction scan** — re-read the task instruction and extract every table or model name
   mentioned as a deliverable. If it has no .sql file, build it — even without a .yml entry.
   Use the task description and source schema DDL as your spec for columns and logic.
3. **Macro scan** — before writing any model, list the files in `macros/` directory. Any `{% macro name(...) %}` defined there can be called from SQL models as `{{ name(...) }}`. Read the macro files to understand what they do — don't reinvent logic that's already in a macro.

Tasks like `activity001` (19 `dataset__*` tables) and `f1001` (most_wins, most_retirements, etc.)
fail specifically because the agent stops at pass 1. Always complete both passes.

## Build the Dependency Graph Before Writing Any SQL
Before writing a single model:
1. List all `.yml` files with model definitions
2. For each model, note its `refs:` dependencies
3. Draw the topological order: sources → staging → core → marts
4. Write and run models in this order — dbt enforces it anyway but knowing the order prevents confusion

If model B refs model A and model A has no .sql file, write A first.

## YAML-to-SQL Workflow
- Every model is defined in a `.yml` file with `name`, `description`, `columns`, and `refs`
- The `refs` section tells you which upstream models to join
- Column names in the YAML are EXACT — your SQL output columns must match them precisely
- The `description` field often hints at the transformation logic (joins, filters, aggregations)

## Column Verification Checklist (run mentally before writing each model)
1. Open the YAML for this model
2. Copy out every name under `columns:` — this is your SELECT output list
3. Your SQL SELECT must alias every output column to EXACTLY these names
4. Run: diff between your SELECT aliases and the YAML column list — zero diff required
5. Common mistake: YAML says `driver_full_name`, SQL says `full_name` — this will FAIL evaluation

## dbt Syntax Essentials
```sql
-- Reference another model (creates dependency)
SELECT * FROM {{ ref('stg_customers') }}

-- Reference a raw source table
SELECT * FROM {{ source('raw', 'orders') }}

-- Materialization config (put at top of .sql file)
{{ config(materialized='table') }}   -- for fact/dim tables
{{ config(materialized='view') }}    -- for staging views
```

## Naming Conventions
- `stg_*` — staging models (light transformations from sources, usually views)
- `dim_*` — dimension tables (entities: customers, products, dates)
- `fct_*` or `fact_*` — fact tables (events: orders, invoices, transactions)
- `obt_*` — one-big-table (wide denormalized joins of facts + dimensions)

## Common Patterns

### Dimension from Staging
```sql
{{ config(materialized='table') }}
SELECT
    s.customer_id,
    s.first_name,
    s.last_name,
    e.first_name AS support_rep_first_name
FROM {{ ref('stg_customer') }} s
LEFT JOIN {{ ref('stg_employee') }} e
    ON s.support_rep_id = e.employee_id
```

### Fact from Staging (passthrough)
```sql
{{ config(materialized='table') }}
SELECT * FROM {{ ref('stg_invoice') }}
```

### OBT (wide join)
```sql
{{ config(materialized='table') }}
SELECT
    f.*,
    d.customer_first_name,
    dd.day_of_week
FROM {{ ref('fct_invoice') }} f
LEFT JOIN {{ ref('dim_customer') }} d ON f.customer_id = d.customer_id
LEFT JOIN {{ ref('dim_date') }} dd ON f.invoice_date = dd.date_key
```

## DuckDB-Specific SQL
- Date arithmetic: `date + INTERVAL '6' DAY` (not `date + 6`)
- `DAYOFWEEK(date)` returns 0=Sunday..6=Saturday
- `ISODOW(date)` returns 1=Monday..7=Sunday
- `STRFTIME(date, '%A')` for day name, `'%b'` for short month
- `DATE_TRUNC('week', date)` for first day of week
- `LAST_DAY(date)` for last day of month
- Use `CAST(x AS DATE)` not `x::date` for portability
- No `DATEADD` function — use `date + INTERVAL`
- String concat: `||` operator or `CONCAT()`

## Debugging dbt Failures
1. Read the FULL error message — it tells you the exact model and line
2. `Compilation Error`: wrong ref name, missing model, YAML mismatch
3. `Database Error`: bad SQL syntax for DuckDB
4. Column mismatch: your SQL columns don't match YAML `columns:` list
5. After fixing, always re-run `dbt run` to verify ALL models pass

## Check for Incomplete/Truncated SQL
Some existing `.sql` files may be incomplete (e.g., truncated CTEs ending with `,`).
Before writing new models, quickly scan existing SQL files — if any end with a trailing comma,
unbalanced parentheses, or are clearly truncated, **fix them first** as other models may depend on them.

## Ephemeral Stub Models — Resolving Missing ref() Targets

When existing staging SQL uses `{{ ref('raw_table') }}` but no `raw_table.sql` exists,
dbt will fail with `Compilation Error: ... not found`.

**Preferred fix: create an ephemeral stub.**

1. Verify the table exists in DuckDB:
   ```sql
   SELECT table_name FROM information_schema.tables WHERE table_name = 'raw_table'
   ```
2. Create `models/raw_table.sql` (or in the same subdirectory as the calling model):
   ```sql
   {{ config(materialized='ephemeral') }}
   select * from main.raw_table
   ```

Ephemeral models inline as CTEs — they create NO database object. They will NOT shadow
or overwrite source data. Safe to use even when the name matches an existing DuckDB table.

**When to use ephemeral vs direct SQL:**
- Ephemeral stub: the existing model you didn't write uses `ref('raw_table')` and you want
  to satisfy that ref without rewriting the calling model.
- Direct `FROM main.raw_table`: you are writing a new model yourself from scratch and no
  other model depends on a ref() to that name.

## Wide Aggregation Pattern
For models with many columns counting categories (e.g., counts by position, status, type):

**Step 1 — Enumerate distinct values first:**
```sql
-- Before writing CASE WHEN, find out what values actually exist:
SELECT DISTINCT position_desc FROM stg_results ORDER BY position_desc
```

**Step 2 — Map each distinct value to the YAML column name, then write CASE WHEN:**
```sql
{{ config(materialized='table') }}
SELECT
    driver_id,
    SUM(CASE WHEN position = 1 THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN position <= 3 THEN 1 ELSE 0 END) AS podiums,
    SUM(CASE WHEN position IS NULL THEN 1 ELSE 0 END) AS dnf,
    COUNT(*) AS total_entries
FROM {{ ref('stg_results') }}
GROUP BY driver_id
```

Rules:
- Use CASE WHEN inside SUM(), not PIVOT. Match column names exactly to YML.
- For status/category columns: enumerate distinct values from source FIRST, then write one CASE WHEN per value.
- Any value not matching a named column goes into the catch-all column (e.g., p21plus, not_classified).
- Do NOT guess category strings — query the source table to get exact casing and spelling.

## JOIN and Filter Correctness

The most common SQL logic error is returning too many rows. Before finalizing any model:

**Choose JOIN type deliberately:**
- INNER JOIN when both sides must match (eliminates non-matching rows — usually what you want)
- LEFT JOIN only when you need to preserve all left-side rows including those with no match
- LEFT JOIN + WHERE right.col IS NOT NULL is the same as INNER JOIN — just write INNER JOIN

**Check for fan-out:**
After writing a JOIN, ask: "Can one left-side row match multiple right-side rows?"
If yes and you don't want expansion, pre-aggregate the right side before joining, or add DISTINCT.

**Verify cardinality after running:**
Run `SELECT COUNT(*) FROM model` and compare to expected:
- Summary model (one row per group): count should equal COUNT(DISTINCT group_key) from source
- If count is higher than expected: tighten JOIN, add WHERE, or fix GROUP BY columns

## Do NOT
- Modify `.yml` files — write SQL that matches the existing YAML
- Use PostgreSQL/MySQL syntax — this is DuckDB
- Skip running `dbt run` — always validate your SQL compiles and runs
- Assume a task is done after writing one model — check ALL yml files for missing SQL
- Create passthrough .sql files named after raw tables — this shadows and destroys source data
