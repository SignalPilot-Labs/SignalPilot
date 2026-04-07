---
description: "Debugging dbt failures — compilation errors, database errors, YAML mismatches, and iterative fix strategies."
---

# dbt Debugging

## Error Types

### Compilation Error
The Jinja/dbt layer failed before SQL reached the database.
- Wrong `ref()` or `source()` name
- Missing model or circular dependency
- Jinja syntax error (unclosed `{{ }}`, wrong macro name)

**Fix:** Check the model name matches exactly — `ref('stg_invoice')` must match a file `stg_invoice.sql`.

### Database Error
SQL compiled but the database rejected it.
- Column doesn't exist
- Type mismatch in JOIN or WHERE
- Syntax not supported by this database engine

**Fix:** Read the error line number, check column names against the actual table schema.

### YAML Column Mismatch
dbt test failures when your SQL output columns don't match the YAML `columns:` list.

**Fix:** Compare your SELECT column aliases against every column name in the YAML — they must be identical.

## Iterative Fix Strategy
1. Read the FULL error message — it tells you the exact model and line
2. Fix ONE thing at a time
3. Re-run `dbt run` after each fix
4. If a model depends on another that failed, fix the upstream model first
5. Use `dbt run --select model_name` to test a single model

## Common dbt Mistakes
- Using `ref('model')` when you need `source('schema', 'table')` for raw data
- Forgetting `{{ config(materialized='table') }}` — defaults to view which may not persist
- Column aliases in SQL don't match YAML column names
- Referencing a model that doesn't have a .sql file yet (build order)
- Modifying .yml files instead of writing correct SQL to match existing YAML
