---
name: dbt-workflow
description: "Load at Step 1 before exploring the project. Covers output shape inference, incremental model handling, and what to trust in YML."
type: skill
---

# dbt Workflow Skill — Explore and Plan

## 1. Output Shape — Read YML Description BEFORE Writing SQL

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
- Identify which source columns to use (e.g. "starting from first position on
  the grid" → use the `grid` column, not qualifying position)
- Understand the business meaning of each column
- Pick the right aggregation logic

But do NOT treat descriptions as literal computation instructions. They may
describe steady-state behavior that doesn't apply on first build, or use
imprecise language. After reading the description, always verify your logic
against the actual source data — query the source tables to confirm which
columns and values produce the expected result.

Write at top of SQL: `-- EXPECTED SHAPE: <row count or formula> — REASON: <quote>`

## 1b. Snapshot Reference Tables BEFORE Building

The starting database contains pre-computed reference tables with correct output.
`dbt run` will overwrite them. **Before your first `dbt run`**, for each target
model that already exists as a table in the database:

```sql
SELECT COUNT(*) FROM <model_name>
```

Record the row count in your `-- EXPECTED SHAPE` comment. If your rebuilt model's
row count doesn't match after `dbt run`, you MUST diff against this reference to
find which rows differ.

## 2. Incremental Models and Period-Over-Period Columns

When a dbt project uses `materialized="incremental"` models, the project is
designed to accumulate state over multiple runs. On a **first run** (full refresh,
no prior state), incremental models build from scratch.

**If you are writing a new model that includes period-over-period metrics
(MoM, WoW, YoY) and the project has not been run incrementally before**:
1. Output rows for the **latest date only**: `WHERE date_col = (SELECT MAX(date_col) FROM source)`
2. Period-over-period columns must be `CAST(NULL AS DOUBLE)` — there is no prior
   aggregated state to compare against. Computing these from raw historical data
   would produce values that don't match the expected first-run output.

**If the model SQL already exists** (not a stub):
- Read the `{% if is_incremental() %}` block to understand the filter logic.
- The code outside that block runs on full refresh.

## 3. What to Trust in YML

**Trust YML for**: column names (exact match required), column descriptions (what
each column represents), ref dependencies (what tables to join).

**YML `not_null` tests on key/dimension columns** (IDs, names, dates, categories)
imply a `WHERE col IS NOT NULL` filter on input data. Do NOT implement this as an
INNER JOIN — use an explicit WHERE clause. `not_null` on metric/aggregate columns
(counts, averages, totals) just asserts the output shouldn't be NULL — don't filter
inputs for those, fix the aggregation instead.

**Do NOT trust YML for**: grain/row count. YML `unique` and `not_null` tests are
assertions that may be aspirational or wrong. Do NOT use `not_null` tests to decide
join type.

Derive the grain from these signals (in priority order):

1. **Unique key structure**: If the YML defines a unique key or surrogate key column,
   examine what it's composed of. A key like `concat(ticker, timestamp)` means the
   grain is (ticker, timestamp) — not (ticker, date). The key tells you exactly
   what combination of values identifies one row.

2. **Column list**: The columns themselves reveal the grain. If a model has both
   a header-level key AND a detail-level key as separate columns, the grain is
   at the detail level.

3. **Upstream model grain**: Check existing upstream models that feed into yours.
   If `bar_executions` produces one row per (ticker, timestamp), your model that
   depends on it likely has the same or coarser grain — not finer.

4. **Source cardinality**: Before writing SQL, query the source tables to check
   how many rows your model should produce:
   `SELECT COUNT(DISTINCT key_col) FROM source_table`
   If your model produces dramatically fewer rows than upstream, your GROUP BY
   is too coarse.

5. **Sibling model row counts**: Check complete models at the same level.

Do NOT deduplicate with ROW_NUMBER to force a `unique` test to pass — if the
data naturally has multiple rows per key, keep them all.
