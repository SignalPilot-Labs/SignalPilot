---
name: dbt_expert
description: "Advanced dbt patterns: output shape inference from YML descriptions (entity+qualifier, top-N rank cutoffs, rolling window vs point-in-time), pre-build cardinality analysis before JOINs, JOIN type selection, boundary filter verification, date format detection (European DD/MM/YYYY)."
type: skill
applicable_dbs: ["duckdb"]
priority: 10
---

# dbt Expert Skill

## Output Shape Inference — Do This BEFORE Writing SQL

Read the model YML description carefully and extract:
- ENTITY: "for each customer/driver/order" → one output row per qualifying entity
- QUALIFIER: "due to returned items" / "with at least one order" → filter, not all rows
  (Use INNER JOIN or qualifying subquery — not all entities)
- RANK CONSTRAINT: "top N" / "ranks the top N" → QUALIFY DENSE_RANK() OVER (...) <= N is mandatory
  Without this clause, all rows are returned regardless of DENSE_RANK logic.
- TEMPORAL SCOPE: "rolling 30-day window" + surrogate_key on date×entity → point-in-time output
  The model should produce ONE output date (the latest), not a row for every historical date.
  Fix: add WHERE <date_col> = (SELECT MAX(<date_col>) FROM <source>)

Write a comment at the top of the SQL body:
  -- EXPECTED SHAPE: <inferred row count or cardinality formula>
  -- REASON: <quote the description phrase that drove this inference>

After dbt run, compare actual row count to inference:
  SELECT COUNT(*) FROM <model>
  If count >> inferred: over-producing (time-series instead of point-in-time, missing cutoff)
  If count << inferred: check for over-filtering or wrong JOIN type

Critical signals:
- "rolling window" + unique_key = date×entity → output has ONE date, not all historical dates
- "top N" or "ranks the top N" → QUALIFY DENSE_RANK() OVER (...) <= N is mandatory
- "for each X" + "with/due to <criterion>" → INNER JOIN or subquery, not all entities
- "MoM"/"WoW" comparison → if result has thousands of dates, rolling window was misimplemented

## Pre-Join Cardinality Check — Run Before Every JOIN

Before writing any JOIN, run this query on the right-side table:
  SELECT COUNT(*), COUNT(DISTINCT <join_key>) FROM <right_table> [WHERE <your_filter>]

If COUNT(*) > COUNT(DISTINCT join_key): right side has duplicates. Pre-aggregate or
deduplicate BEFORE joining, or your model will fan-out silently.

For UNION-based models: verify each source branch contributes the expected rows:
  SELECT COUNT(*) FROM <source_table> [WHERE <domain_filter>]
Compare to related tables — if drug_exposure has 663 rows and procedures has 144,
the UNION total should be exactly 807. Count each branch before writing the UNION.

## JOIN Type Selection

DEFAULT TO LEFT JOIN for reporting and aggregation models that need to preserve all entities.
- LEFT JOIN: required when left table is the spine (all customers, all products, all admins, all dates)
  Example: admin metrics must show ALL admins, even those with zero conversations.
  Start FROM the dimension table (all entities) and LEFT JOIN to the fact/event table.
- INNER JOIN: only when the task description explicitly excludes non-matching entities
  (e.g., "customers WITH orders" — only customers who have orders)
- LEFT JOIN + WHERE right.col IS NOT NULL silently becomes INNER JOIN — avoid this pattern
- When output row count < expected: first check if INNER JOIN should be LEFT JOIN

### JOIN Direction — Which Table Goes on the LEFT?

Before writing any two-table JOIN, count BOTH tables:
```sql
SELECT COUNT(*) FROM table_a;  -- e.g., 874
SELECT COUNT(*) FROM table_b;  -- e.g., 461
```
The table that defines ALL instances of the output entity (broader domain coverage) MUST be the LEFT/driving table. A crosswalk, mapping, or enrichment table that only covers a subset should always be on the RIGHT.

Example: If model description says "one row per taxonomy code" and `nucc_taxonomy` has 874 codes but `medicare_crosswalk` only covers 460 of them:
```sql
-- CORRECT: drive from the complete table
FROM nucc_taxonomy LEFT JOIN medicare_crosswalk ON ...
-- WRONG: drives from partial-coverage table, silently drops 414 codes
FROM medicare_crosswalk LEFT JOIN nucc_taxonomy ON ...
```

When the right-side table has duplicates per join key (one-to-many), deduplicate BEFORE joining or use a window function to pick one match per key.

## Column Value Mapping — Preserve Source Values

When joining a fact table to a lookup/mapping table to get descriptive names:
- If the source already has the value you need (e.g., territory name), use the SOURCE value directly
- Only use the lookup table for enrichment columns that don't exist in the source
- Common mistake: replacing a source column with a remapped value from a lookup table when the gold expects the original

Example: If source has `territory = 'Turkey'` and a country_codes table maps it to `'Türkiye'`:
```sql
-- CORRECT: keep raw source value for territory_long, use lookup only for new columns
SELECT src.territory AS territory_long, cc.country_code, cc.region, cc.sub_region
-- WRONG: replace source value with lookup value
SELECT cc.alternative_country_name AS territory_long
```

When in doubt, verify by checking a few sample values after dbt run.

## Boundary Filter Verification

For any WHERE clause on a date or integer range, verify the inclusive/exclusive boundary:
  SELECT COUNT(*) FROM source WHERE <filter>
Confirm the row count matches your model's expected output before finishing.

## Date Format Detection

When a source column contains dates, ALWAYS check sample values with explore_table first.
European dates (DD/MM/YYYY) must use STRPTIME(col, '%d/%m/%Y').
Never assume MM/DD/YYYY — check the data. If day > 12 in any row, it is DD/MM format.

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

Tasks that require building many dataset models or multiple aggregation tables fail when the agent stops at YAML discovery alone. Always complete both passes.

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

### YML Description as Semantic Contract

Before writing any SQL, read the `description:` field of each priority model and extract its cardinality contract:

- **Entity + qualifier pattern** — "revenue lost due to returned items" or "customers with at least one order":
  Only entities meeting the criterion appear in output. Use INNER JOIN or a qualifying subquery — not all entities.

- **"top N" / "ranks the top N"** — a QUALIFY or WHERE rank filter is mandatory:
  ```sql
  QUALIFY DENSE_RANK() OVER (ORDER BY metric DESC) <= N
  ```
  Without this clause, all rows are returned regardless of DENSE_RANK logic above.

- **"rolling window" + `unique_key` on date×entity** — point-in-time, not time-series:
  The model should produce ONE output date (the latest/current), not a row for every historical date.
  If your model produces thousands of dates, the rolling window was misimplemented.
  Fix: add `WHERE <date_col> = (SELECT MAX(<date_col>) FROM <source>)`.

After inferring the expected output shape, add a comment at the top of the SQL:
```sql
-- EXPECTED SHAPE: <e.g., 20 rows — one per top-ranked driver>
-- REASON: <quote from description, e.g., "ranks the top 20 drivers">
```
Then verify `SELECT COUNT(*) FROM <model>` matches after `dbt run`.

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

## Row Count Audit — Mandatory After Every dbt Run

After `dbt run` succeeds on any priority model, run these two queries before moving on:

```sql
-- Check for fan-out:
SELECT COUNT(*) FROM {{ ref('my_model') }};
SELECT COUNT(DISTINCT primary_key) FROM source_table;
-- If model count > source distinct count: FAN-OUT — find and fix before finishing.

-- If too few rows — find the culprit condition:
SELECT COUNT(*) FROM source_table;                         -- expected
SELECT COUNT(*) FROM source_table WHERE your_condition;    -- if drops: condition is wrong
```

A passing `dbt run` with wrong row counts is a failed evaluation. This audit takes 2 tool calls. Always run it.

## Do NOT
- Modify `.yml` files — write SQL that matches the existing YAML
- Use PostgreSQL/MySQL syntax — this is DuckDB
- Skip running `dbt run` — always validate your SQL compiles and runs
- Assume a task is done after writing one model — check ALL yml files for missing SQL
- Create passthrough .sql files named after raw tables — this shadows and destroys source data
