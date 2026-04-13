---
name: dbt-date-spines
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
