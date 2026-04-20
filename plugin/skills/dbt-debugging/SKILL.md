---
name: dbt-debugging
description: "Load when dbt run or dbt parse fails. Covers YML duplicate patches, ref errors, passthrough model warnings, current_date fixes, DuckDB error messages, and zero-row diagnosis."
type: skill
---

# dbt Debugging Skill

## 1. Duplicate YML Patches (VERY COMMON)

dbt fails with "Duplicate patch" when the same model appears in multiple YML files.
Fix in ONE pass:
1. Glob `models/**/*.yml` to find all YML files
2. Keep the entry with the full contract (descriptions, refs, columns) — usually in a subdirectory YML
3. Remove the duplicate from `schema.yml` (which typically only has tests)

## 2. Ref Not Found

If `Compilation Error: node not found for ref()`:
- Check if the name is a raw DuckDB table: `SELECT table_name FROM information_schema.tables WHERE table_name = 'name'`
- If yes, create an ephemeral stub:
  ```sql
  {{ config(materialized='ephemeral') }}
  select * from main.<name>
  ```
- If ephemeral causes CTE issues, replace `{{ ref('name') }}` with `main.name` directly

## 3. Passthrough Model Warning

NEVER create `.sql` files named after raw tables (e.g. `circuits.sql`, `results.sql`).
This DESTROYS source data by replacing it with a materialized model.
Fix: add `schema: main` to the source definition in YML instead.

## 4. current_date Fix

If `dbt_project_map` warns about `current_date` usage:
1. Call `get_date_boundaries` — find the column marked "USE THIS"
2. Replace `current_date`/`now()` with `(SELECT MAX(<col>) FROM {{ ref('<table>') }})`
3. For package models: create `models/<name>.sql`, paste full SQL, replace current_date

## 5. ROW_NUMBER Non-Determinism

If `dbt_project_map` warns about ROW_NUMBER/RANK:
1. Check if ORDER BY columns are unique within each partition
2. If not unique, append the primary key to ORDER BY
3. Re-run `dbt run --select <model>`

## 6. DuckDB Error Messages

| Error | Fix |
|-------|-----|
| `invalid date field format` | `STRPTIME(col, '%d/%m/%Y')::DATE` |
| `Table does not exist` | Check actual names with `describe_table` |
| `column not found` | Check exact names — case matters in DuckDB |
| `Cannot mix TIMESTAMP and INTEGER` | Cast both args to same type |
| `No function matches DOUBLE / VARCHAR` | Add explicit `CAST()` |
| `fivetran_utils is undefined` | Run `dbt deps` (only if `packages.yml` exists) |

## 7. Zero-Row Model

Binary search: comment out WHERE clauses and JOINs one at a time to find which
condition drops all rows. Most common cause: INNER JOIN where LEFT JOIN is needed.

## 8. Fan-Out (Too Many Rows)

1. Diagnose: `SELECT join_key, COUNT(*) FROM right_table GROUP BY 1 HAVING COUNT(*) > 1`
2. Fix A: pre-aggregate right table before joining
3. Fix B: `SELECT DISTINCT` (if valid for the grain)
4. Fix C: `ROW_NUMBER()` dedup pattern
