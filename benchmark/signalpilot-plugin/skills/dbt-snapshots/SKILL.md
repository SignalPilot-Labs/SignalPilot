---
name: dbt-snapshots
description: "Load when task involves dbt snapshots, SCD Type 2, or tracking data changes over time. Covers strategy selection, column casing, verification, and common pitfalls."
disable-model-invocation: false
allowed-tools: Bash(dbt *)
---

# dbt Snapshots - SCD Type 2

## 1. File Location

Place snapshot files in `snapshots/`, NOT `models/`.
Verify `snapshot-paths: ["snapshots"]` exists in `dbt_project.yml`.

## 2. Strategy Selection

**Choose the strategy BEFORE writing the snapshot file.**

Query the candidate timestamp column first:
```sql
SELECT COUNT(DISTINCT updated_at), MIN(updated_at), MAX(updated_at)
FROM my_source_table
```

- If `COUNT(DISTINCT updated_at) = 1` or all values are frozen (e.g., `1980-01-01`), the column is unreliable - a frozen timestamp means `dbt snapshot` will never detect changes.
- If values vary and reflect real mutation times, `strategy='timestamp'` is valid.

| Condition | Strategy |
|-----------|----------|
| `updated_at` has changing, meaningful values | `strategy='timestamp'`, `updated_at='UPDATED_AT'` |
| `updated_at` frozen at a single constant value (COUNT(DISTINCT)=1) | `strategy='check'`, `check_cols='all'` - a column stuck at one value will never detect changes |
| No `updated_at` column at all | `strategy='check'`, `check_cols='all'` |

Default to `strategy='check'` with `check_cols='all'` when uncertain - it always works.

Do NOT rationalize a frozen timestamp as valid business data. `1980-01-01` on every row is a data quality artifact, not a real date.

## 3. Column Casing

Snapshot `unique_key`, `updated_at`, and `check_cols` must match the EXACT case of the source columns.

Query column names before writing the config:
```sql
DESCRIBE my_source_table
```

Wrong: `unique_key='id'` when the source column is `ID`.
Right: `unique_key='ID'`.

DuckDB and Snowflake snapshot configs are case-sensitive. A casing mismatch silently produces zero change detection.

## 4. Writing the Snapshot Block

SELECT explicit columns - not `SELECT *`. Include only business columns.
Use raw source column names - do NOT alias them (e.g., `SELECT ID`, not
`SELECT ID AS HOST_ID`). The snapshot output columns must match the source
for `unique_key` and `check_cols` to work.

```sql
{% snapshot snap__employees %}
{{
    config(
        target_schema='main',
        unique_key='EMPLOYEE_ID',
        strategy='check',
        check_cols='all'
    )
}}
SELECT EMPLOYEE_ID, DEPARTMENT, TITLE, SALARY
FROM {{ source('hr', 'employees') }}
{% endsnapshot %}
```

Set `target_schema` to the project's default schema (`'main'` for DuckDB).

## 5. Data Type Awareness

Query actual column values before writing predicates:
```sql
SELECT DISTINCT IS_ACTIVE FROM my_source_table LIMIT 10
```

- If values are `'t'`/`'f'` (strings), compare with `= 't'`, NOT `= TRUE`.
- If values are `true`/`false` (booleans), compare with `= TRUE`.

Getting this wrong silently filters to zero rows.

## 6. Running Snapshots

Run `dbt snapshot` - not `dbt run`. `dbt run` ignores snapshot files.

If the task involves tracking changes over time, run `dbt snapshot` once per mutation phase. A single run captures only the initial state.

## 7. Verification

After `dbt snapshot`, verify history was captured:
```sql
SELECT COUNT(*) AS total, COUNT(DISTINCT EMPLOYEE_ID) AS distinct_keys
FROM main.snap__employees
```

- If `total = distinct_keys`, zero changes were detected - the strategy or config is wrong. Go back to Section 2.
- Query `dbt_valid_to`: if ALL values are NULL, only the initial load exists - no mutations were tracked.

Also verify SCD2 columns exist: `dbt_valid_from`, `dbt_valid_to`, `dbt_scd_id`, `dbt_updated_at`.

## 8. Downstream Models

Reference snapshots like any model: `{{ ref('snap__employees') }}`.

- For **current state** (latest version of each row): `WHERE dbt_valid_to IS NULL`.
- For **full change history** (e.g., "who has ever been X"): use ALL rows. Use `LAG()` over `dbt_valid_from` to detect status transitions.
- A snapshot table can hold history loaded before your run, even when `snapshots/` is absent. Probe it BEFORE `dbt snapshot`: `SELECT COUNT(*), COUNT(DISTINCT dbt_valid_from) FROM main.snap__employees`. Multiple `dbt_valid_from` values are pre-existing history to build on, NOT the Section 7 zero-change failure - compute metrics over all versions.
- For a "first time in state X" metric (not a transition count), use `MIN(dbt_valid_from)` filtered to state X. A row already in state X at the earliest version still has a first-observed time, so do NOT require an earlier different-state version.

## Rules

- NEVER use `run_in_background` or `&` with `dbt snapshot` - it holds a write lock.
- Do NOT modify `.yml` files for snapshots - snapshot config lives in the `.sql` block.
- A single `dbt snapshot` run with no prior state produces only the initial load, not history. This is expected - history builds across multiple runs with source mutations between them.
