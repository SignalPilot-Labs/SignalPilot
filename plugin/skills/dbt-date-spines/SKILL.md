---
name: dbt-date-spines
description: "Fix current_date/now() hazards in dbt date spine models. Replaces nondeterministic date references with data-driven boundaries from get_date_boundaries."
type: skill
---

# dbt Date Spine Hazard — Fixing current_date in Model Files

## When This Applies
- `dbt_project_map` reports "WARNING: Models use current_date"
- `dbt run` produces far more rows than expected in a date-spine model

These are pre-shipped model SQL files in `models/` — you have direct write access.
For general date spine syntax, see `duckdb-sql` skill section 2.

## Fix Pattern

Edit the model SQL directly. Replace `current_date`/`current_timestamp`/`now()` with a data-driven endpoint — a subquery from the primary fact table:

```sql
-- Before:  ... CURRENT_DATE ...
-- After:   ... (SELECT MAX(order_date) FROM {{ ref('stg_orders') }}) ...
```

Use the fact table with the most rows, or the one referenced in the task instruction.

## Package Model Override

If the flagged file is in `dbt_packages/` (marked "PACKAGE MODEL" in the warning):
1. Read the full SQL from the package model file
2. Create `models/<same_filename>.sql` — dbt prioritizes local models over package models
3. Paste the entire package SQL into the new file and replace `current_date` with the data-driven endpoint
4. Add `{{ config(materialized='table') }}` at the top

Example: if `dbt_packages/shopify_source/models/stg_shopify__order.sql` uses `current_date`:
```sql
-- models/stg_shopify__order.sql  (local override — copy ENTIRE package SQL here)
{{ config(materialized='table') }}
-- Replace current_date with a data-driven endpoint:
-- (SELECT MAX(order_date) FROM {{ ref('stg_orders') }})
```

Do NOT edit files inside `dbt_packages/` directly — `dbt deps` will overwrite your changes.

## Finding the Right Date

Call `mcp__signalpilot__get_date_boundaries(connection_name="<id>")`.
Use the primary fact table's max date (marked "USE THIS"). Never use the global max — dimension tables often have later dates.

## Verification

```
dbt run --select <model_name>
```
```sql
SELECT MIN(date_col), MAX(date_col), COUNT(*) FROM <model_name>
```
The spine's max date must match the source data's endpoint, not today's date.
