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
2. Keep the entry with the full contract (descriptions, refs, columns) - usually in a subdirectory YML
3. Remove the duplicate from `schema.yml` (which typically only has tests)

## 2. Ref Not Found

When a missing `ref()` has a same-name physical relation, add an ephemeral wrapper selecting that fully qualified relation because this repairs graph resolution without changing identity. Do not redirect an existing `ref()` or source to a different relation because that changes population.

## 3. Raw-Relation Name Collision

Do not create a persistent model with the same qualified name as a raw relation because materialization overwrites its input. Add a missing source schema only when it qualifies the same configured identifier because that preserves identity.

## 4. current_date Fix

If `dbt_project_map` warns about `current_date` usage:
1. Call `get_date_boundaries` - find the column marked "USE THIS"
2. Replace `current_date`/`now()` with `(SELECT MAX(<col>) FROM {{ ref('<table>') }})`
3. For package models: create `models/<name>.sql`, paste full SQL, replace current_date

Keep `current_date` where a YML description anchors logic to the present ('current fiscal year', 'as of today', 'active now') - the warning is about stale date spines and date caps, not present-anchored business rules.

## 5. DuckDB Error Messages

| Error | Fix |
|-------|-----|
| `invalid date field format` | `STRPTIME(col, '%d/%m/%Y')::DATE` |
| `Table does not exist` | Check actual names with `describe_table` |
| `column not found` | Check exact names - case matters in DuckDB |
| `Cannot mix TIMESTAMP and INTEGER` | Cast both args to same type |
| `No function matches DOUBLE / VARCHAR` | Add explicit `CAST()` |
| `fivetran_utils is undefined` | Run `dbt deps` (only if `packages.yml` exists) |

## 6. Package Model Build Failures

If `dbt run` fails on a model inside `dbt_packages/` with a type error
(e.g., `date_trunc` on an INTEGER, `No function matches`), you MUST fix
the package SQL file directly. The sandbox has no internet, so you cannot
reinstall the package. Read the failing SQL, find the type mismatch, and
add the appropriate CAST or conversion (e.g., `to_timestamp(epoch_col)`
for epoch integers, `CAST(col AS DATE)` for type mismatches). Broken
upstream models block everything downstream.

## 7. Zero-Row Model

Treat a successful zero-row relation as valid unless the task, YML, `prebuild_state.md`, or complete sibling requires rows because empty population is not a build failure. Diagnose filters and joins only after that evidence exists. Do not redirect a configured source merely to populate it.

## 8. Fan-Out (Too Many Rows)

1. Diagnose: `SELECT join_key, COUNT(*) FROM right_table GROUP BY 1 HAVING COUNT(*) > 1`
2. Fix A: pre-aggregate right table before joining
3. Fix B: `SELECT DISTINCT` (if valid for the grain)
4. Fix C: `ROW_NUMBER()` dedup pattern
