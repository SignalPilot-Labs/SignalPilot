---
name: dbt-workflow
description: "Load FIRST before any dbt project work. Covers the full 5-step dbt workflow: project scanning, mapping, validation, contract understanding, SQL writing, and verification. Also covers output shape inference, incremental model handling, and what to trust in YML."
disable-model-invocation: false
allowed-tools: Bash(dbt *) Bash(python3 *)
---

# dbt Workflow Skill — Full Project Lifecycle

## Overview

This skill orchestrates the complete dbt project workflow. Load it FIRST whenever
working on a dbt project — it contains rules that affect how you interpret everything.

## Project Scan Tool

To scan a dbt project, run:
```bash
python3 "${CLAUDE_SKILL_DIR}/scan_project.py" "<project_directory>"
```
This returns: models to build, stubs to rewrite, dependencies, required columns,
sources, macros, and current_date hazards. Run this FIRST in Step 1.

## The 5-Step Workflow

### Step 1 — Map the project
Run the project scan tool above with the dbt project directory, then call
`mcp__signalpilot__dbt_project_map project_dir="<your_project_dir>"`.
The work order at the bottom is your plan. Use the project scan to identify:
- STUBS TO REWRITE (models with placeholder SQL)
- MODELS TO BUILD (models defined in YML but missing SQL)
- DEPENDENCIES (build order)
- REQUIRED COLUMNS (exact match from YML contracts)

### Step 2 — Validate
Call `mcp__signalpilot__dbt_project_validate project_dir="<your_project_dir>"`.
Fix any parse errors before writing SQL.

### Step 3 — Understand contracts + read siblings
For each model in the work order:
1. Call `dbt_project_map` with `focus="model:<name>"` for the column contract
2. If `reference_snapshot.md` exists, check it for the pre-existing row count and
   sample data. If present, that row count is your target.
3. If no reference exists, estimate the expected row count by querying source data:
   `SELECT COUNT(DISTINCT <grain_key>) FROM <source>` as an UPPER BOUND.
4. Read the SQL of any complete sibling model in the same directory that shares
   column names with your model. You MUST read sibling SQL before writing — do not
   skip this step.

### Step 4 — Write and Build ALL Models
Load the `/signalpilot-dbt:dbt-write` skill + the SQL skill for your database
(e.g. `/signalpilot-dbt:duckdb-sql` for DuckDB). Write SQL for EVERY model in
the work order. For each model (in dependency order):
1. Read the YML contract — column names must match EXACTLY
2. Write the SQL
3. Run `dbt run --select <model>` to build it

After all stubs are written, rebuild them AND their downstream dependents:
`dbt run --select <stub1>+ <stub2>+` (the `+` suffix includes downstream
models that depend on the stubs you wrote).

If errors, load `/signalpilot-dbt:dbt-debugging` skill and fix. Do NOT run a bare
`dbt run` — it rebuilds ALL models including pre-existing ones you didn't touch,
which can change surrogate key assignments and break FK relationships.

### Step 5 — Verify
After your final `dbt run` completes, verify all models:
1. Confirm the database is queryable: `query_database` with `SELECT 1`
2. Use the Agent tool with `subagent_type="verifier"` to check all models you built
3. STOP when the verifier subagent completes successfully

---

## Output Shape — Read YML Description BEFORE Writing SQL

Extract from `description:` field:
- **ENTITY**: "for each customer/driver/order" → one row per qualifying entity
- **QUALIFIER**: "due to returned items" / "with at least one order" → filter or INNER JOIN
- **RANK CONSTRAINT**: "top N" / "ranks the top N" → exactly N output rows. Filter
  with `ROW_NUMBER() ... <= N` using a deterministic tiebreaker (add primary key to
  ORDER BY). Do NOT use DENSE_RANK for filtering — it can return more than N rows.
- **TEMPORAL SCOPE**: "rolling window", "MoM", "WoW", or "month-over-month" in the
  description → ONE output date (latest), not all historical dates. Filter with
  `WHERE date_col = (SELECT MAX(date_col) FROM source)`.
- **PERIOD-OVER-PERIOD**: If the description mentions MoM, WoW, YoY comparisons
  AND you are writing this model from scratch (stub/missing), the comparison column
  must be `CAST(NULL AS DOUBLE)` — see rule below.

**How to read YML descriptions:** Descriptions tell you what the data MEANS, not
what code to write. Use them to:
- Identify which source columns to use
- Understand the business meaning of each column
- Pick the right aggregation logic

But do NOT treat descriptions as literal computation instructions. After reading
the description, always verify your logic against the actual source data.

Write at top of SQL: `-- EXPECTED SHAPE: <row count or formula> — REASON: <quote>`

## Incremental Models and Period-Over-Period Columns

When a dbt project uses `materialized="incremental"` models, the project is
designed to accumulate state over multiple runs. On a **first run** (full refresh,
no prior state), incremental models build from scratch.

**If you are writing a new model that includes period-over-period metrics
(MoM, WoW, YoY) and the project has not been run incrementally before**:
1. Output rows for the **latest date only**: `WHERE date_col = (SELECT MAX(date_col) FROM source)`
2. Period-over-period columns must be `CAST(NULL AS DOUBLE)` — there is no prior
   aggregated state to compare against.

## What to Trust in YML

**Trust YML for**: column names (exact match required), column descriptions (what
each column represents), ref dependencies (what tables to join).

**YML `not_null` tests on key/dimension columns** (IDs, names, dates, categories)
imply a `WHERE col IS NOT NULL` filter on input data. `not_null` on metric/aggregate
columns just asserts the output shouldn't be NULL — don't filter inputs for those.

**Do NOT trust YML for**: grain/row count. YML `unique` and `not_null` tests are
assertions that may be aspirational or wrong.

Derive the grain from these signals (in priority order):
1. **Unique key structure**: If the YML defines a unique/surrogate key, examine its composition
2. **Column list**: The columns themselves reveal the grain
3. **Upstream model grain**: Check existing upstream models
4. **Source cardinality**: Query source tables to check expected row count
5. **Sibling model row counts**: Check complete models at the same level

Do NOT deduplicate with ROW_NUMBER to force a `unique` test to pass.

## Rules

- NEVER run `dbt` commands with `run_in_background` or `&` — dbt holds a database
  write lock while running
- Do NOT modify `.yml` files unless fixing a missing `schema:` in a source definition
- Do NOT guess column names — use the YML contract as source of truth
- Do NOT install external packages — all dbt packages are pre-bundled in dbt_packages/
