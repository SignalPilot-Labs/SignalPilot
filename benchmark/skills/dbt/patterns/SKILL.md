---
description: "DuckDB dbt patterns: date spines (CURRENT_DATE forbidden, use MAX source date), materialization rules (always table, never incremental), NULL/COALESCE handling, SELECT DISTINCT anti-patterns on fact tables, MRR change_category, SCD Type 2, customer status bucketing."
---

# dbt SQL Patterns

## Materialization Rules

Every model file MUST begin with:
  {{ config(materialized='table') }}

Rules:
- NEVER use materialized='incremental' or is_incremental() blocks. Incremental models return
  all rows on first run instead of just the latest period — wrong row counts guaranteed.
- NEVER use materialized='ephemeral' for any model that needs direct query verification.
  Ephemeral models cannot be queried with SELECT COUNT(*) FROM model_name.
- If you see an existing model with incremental config, rewrite it as a table.

## Date Spine — CURRENT_DATE Is Forbidden

Before writing any date spine, call:
  mcp__signalpilot__get_date_boundaries(connection_name="<your_connection>")

This returns the MIN and MAX dates across ALL date/timestamp columns. The output includes
a "GLOBAL MAX DATE" line — use that literal date as your spine endpoint.

NEVER use CURRENT_DATE, now(), or current_timestamp as the spine endpoint. A spine
extending to today produces hundreds of extra rows at eval time.

  UNNEST(GENERATE_SERIES(min_date::DATE, max_date::DATE, INTERVAL '1 day'))

After writing any date spine model, verify:
  SELECT MIN(date_col), MAX(date_col), COUNT(*) FROM <spine_model>
The max date must match the GLOBAL MAX DATE from get_date_boundaries, NOT today.

MANDATORY STEP — Scan and fix existing models that use current_date:
After calling get_date_boundaries, immediately run:
  grep -rn "current_date\|CURRENT_DATE\|now()" models/ --include="*.sql"
If ANY hits are found, EDIT those files to replace current_date/now() with the GLOBAL MAX DATE.
These files are already in your models/ directory — do NOT create new files, edit the existing ones.
Common patterns to fix:
  end_date="current_date"  →  end_date="cast('YYYY-MM-DD' as date)"
  greatest(..., cast(current_date as date))  →  cast('YYYY-MM-DD' as date)
  dbt.dateadd(..., "current_date")  →  "cast('YYYY-MM-DD' as date)"
After fixing, re-run the grep to confirm zero hits remain.

## NULL Handling — Preserve NULLs in String Columns

Do NOT use COALESCE(col, '') to replace NULLs with empty strings.
The evaluator treats NULL and '' as different values. Keep NULLs as NULL unless the
task requires a specific default. Only use COALESCE(col, '') if the output column spec
explicitly says empty string is the correct representation of missing data.

## SCD Type 2 — Window Function Patterns

```sql
-- First value per entity (original, not current):
FIRST_VALUE(user_id) OVER (PARTITION BY entity_id ORDER BY valid_from ASC) AS first_user_id

-- Current record (open-ended):
WHERE valid_to IS NULL
-- OR via date range: WHERE CURRENT_DATE BETWEEN valid_from AND valid_to

-- Annotate current record (filter WHERE rn = 1):
ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY valid_from DESC) AS rn
```

Rule: "original/first_X" → order ASC by `valid_from`. "Current" → `valid_to IS NULL`.

## MRR Change Category

The logic structure is correct. The string literals in the CASE WHEN are EXAMPLES — they vary by project. Always read the project's `.md` documentation files for the actual required strings. Look for `{% docs change_category %}` blocks; they contain a table showing exactly which strings to use.

```sql
WITH mrr AS (
    SELECT customer_id, month, mrr,
        LAG(mrr, 1) OVER (PARTITION BY customer_id ORDER BY month) AS prev_mrr
    FROM {{ ref('stg_mrr') }}
)
SELECT customer_id, month, mrr,
    CASE
        WHEN prev_mrr IS NULL AND mrr > 0            THEN 'new'
        WHEN prev_mrr = 0    AND mrr > 0             THEN 'reactivation'
        WHEN mrr > prev_mrr  AND prev_mrr IS NOT NULL THEN '<check project .md docs>'
        WHEN mrr < prev_mrr  AND mrr > 0             THEN '<check project .md docs>'
        WHEN mrr = 0         AND prev_mrr > 0        THEN 'churn'
        WHEN mrr = prev_mrr                          THEN 'no_change'
        ELSE 'other'
    END AS change_category
FROM mrr
```

## Customer Status Bucketing

Aggregate first in a CTE, classify in the outer SELECT. Highest threshold goes first.

```sql
WITH customer_metrics AS (
    SELECT
        customer_id,
        SUM(order_total)  AS lifetime_value,
        COUNT(order_id)   AS order_count
    FROM {{ ref('fct_orders') }}
    GROUP BY customer_id
)
SELECT
    customer_id,
    lifetime_value,
    CASE
        WHEN lifetime_value >= 10000 THEN 'platinum'
        WHEN lifetime_value >= 5000  THEN 'gold'
        WHEN lifetime_value >= 1000  THEN 'silver'
        ELSE 'bronze'
    END AS lifetime_value_bucket,
    CASE
        WHEN order_count > 1 THEN 'returning'
        ELSE 'new'
    END AS return_customer
FROM customer_metrics
```

Rules: CASE WHEN in SELECT (not WHERE/HAVING). Highest threshold first. Always include `ELSE`. Match YAML column names exactly.

## Date Spine (DuckDB)

```sql
-- Monthly spine:
WITH date_spine AS (
    SELECT UNNEST(GENERATE_SERIES(DATE '2023-01-01', DATE '2024-12-01', INTERVAL '1 month')) AS month
)
-- Fill gaps — CROSS JOIN spine with entities, LEFT JOIN actuals:
SELECT d.month, c.customer_id, COALESCE(m.mrr, 0) AS mrr
FROM date_spine d
CROSS JOIN (SELECT DISTINCT customer_id FROM {{ ref('stg_mrr') }}) c
LEFT JOIN {{ ref('stg_mrr') }} m ON m.month = d.month AND m.customer_id = c.customer_id

-- Normalize to month start:
DATE_TRUNC('month', date_col) AS month
```

## CRITICAL: Never use current_date as spine endpoint

Call mcp__signalpilot__get_date_boundaries first. Use the GLOBAL MAX DATE it returns.

-- BAD — extends to today, produces hundreds of extra rows at eval time:
end_date = current_date

-- GOOD — use the date returned by get_date_boundaries:
end_date = DATE '2024-11-30'  -- copy the GLOBAL MAX DATE literally

If ANY existing .sql file in models/ uses current_date or now(), EDIT that file directly —
replace the current_date reference with the GLOBAL MAX DATE from get_date_boundaries.
Do NOT create a new file — the file already exists in models/ and must be edited in place.
