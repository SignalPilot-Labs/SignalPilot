---
description: "DuckDB-specific SQL patterns for SCD Type 2 window functions, MRR change_category categorization, customer status bucketing, and date spine generation."
---

# dbt SQL Patterns

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

## Customer Status Bucketing (tpch001 pattern)

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
