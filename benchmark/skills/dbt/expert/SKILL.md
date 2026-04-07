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

## YAML-to-SQL Workflow
- Every model is defined in a `.yml` file with `name`, `description`, `columns`, and `refs`
- The `refs` section tells you which upstream models to join
- Column names in the YAML are EXACT — your SQL output columns must match them precisely
- The `description` field often hints at the transformation logic (joins, filters, aggregations)

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

## Wide Aggregation Pattern
For models with many columns counting categories (e.g., counts by position, status, type):
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
Use CASE WHEN inside SUM(), not PIVOT. Match column names exactly to YML.

## Do NOT
- Modify `.yml` files — write SQL that matches the existing YAML
- Use PostgreSQL/MySQL syntax — this is DuckDB
- Skip running `dbt run` — always validate your SQL compiles and runs
- Assume a task is done after writing one model — check ALL yml files for missing SQL
