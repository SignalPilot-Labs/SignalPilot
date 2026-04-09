---
name: duckdb-sql
description: "Use this skill when writing DuckDB SQL. Covers syntax that differs from PostgreSQL/MySQL: INTEGER division truncates (cast numerator to DOUBLE), DATE_TRUNC returns TIMESTAMP not DATE, INTERVAL requires quoted syntax ('1' DAY not 1 DAY), DENSE_RANK vs ROW_NUMBER for ties, date parsing with STRPTIME for non-ISO formats (European DD/MM/YYYY), GENERATE_SERIES for date spines (CURRENT_DATE is forbidden — use get_date_boundaries to get the GLOBAL MAX DATE), string functions, type casting, UNPIVOT/PIVOT, and QUALIFY clause for window-function filters."
type: skill
---

# DuckDB SQL Skill

## 1. Critical Gotchas — Read These First

- **Integer division**: `5/2 = 2`. Fix: `CAST(numerator AS DOUBLE) / denominator`.
- **DATE_TRUNC returns TIMESTAMP**: wrap with `CAST(DATE_TRUNC('month', col) AS DATE)` when YML column is DATE.
- **INTERVAL requires quotes**: `INTERVAL '1' DAY` not `INTERVAL 1 DAY`.
- **No DATEADD**: use `date + INTERVAL '1' DAY`. **No DATEDIFF**: use `DATE_DIFF('unit', start, end)`.
- **Date subtraction returns INTERVAL**, not integer — use `DATE_DIFF`.
- **SELECT DISTINCT ban on fact tables** — use `ROW_NUMBER()` instead.
- **SUM(NULL) = NULL**, not 0.
- Do not `ROUND()` unless required. Do not `COALESCE(col, '')` in dbt models.

## 2. Date Spine — CURRENT_DATE Is Forbidden

Before writing any date spine:
1. Call `mcp__signalpilot__get_date_boundaries(connection_name="<id>")` first.
2. Use the GLOBAL MAX DATE as endpoint:
   ```sql
   UNNEST(GENERATE_SERIES(min_date::DATE, max_date::DATE, INTERVAL '1 day'))
   ```
3. Verify: `SELECT MIN(date_col), MAX(date_col), COUNT(*) FROM spine_model` — max must match GLOBAL MAX DATE.
4. If spine row count is still wrong: query the specific source table for its own `MAX(date_col)` and use that instead.
5. Scan existing models for `current_date`/`now()`: after calling get_date_boundaries, grep and edit any hits directly.

Never use `CURRENT_DATE`, `now()`, or hardcoded date ranges as spine endpoints.

## 3. Date Parsing

- `STRPTIME(col, '%d/%m/%Y')::DATE` for European format (DD/MM/YYYY).
- `TRY_STRPTIME` returns NULL on failure.
- Never `CAST(date_str AS DATE)` on non-ISO strings.
- Always `explore_table` to check sample values — if any day value > 12, it is DD/MM format.

## 4. Type Casting

```sql
CAST(x AS INTEGER)
CAST(x AS DOUBLE)
CAST(x AS VARCHAR)
CAST(x AS DATE)
CAST(x AS TIMESTAMP)
TRY_CAST(x AS INTEGER)     -- returns NULL on failure
```

## 5. String Functions

```sql
CONCAT(a, ' ', b)           -- or a || ' ' || b
LENGTH(s)
LOWER(s), UPPER(s)
TRIM(s), LTRIM(s), RTRIM(s)
REPLACE(s, 'old', 'new')
SUBSTRING(s, start, len)
REGEXP_MATCHES(s, pattern)  -- returns bool
STRING_AGG(col, ', ')       -- with separator
```

## 6. Aggregation

```sql
COUNT(*), COUNT(DISTINCT col)
SUM(col), AVG(col), MIN(col), MAX(col)
MEDIAN(col), QUANTILE_CONT(col, 0.95)
LIST(col), ARRAY_AGG(col)   -- collect into list
FIRST(col), LAST(col)       -- first/last in group
```

## 7. Window Functions and QUALIFY

```sql
ROW_NUMBER() OVER (PARTITION BY g ORDER BY o)
RANK() OVER (ORDER BY col DESC)
DENSE_RANK() OVER (ORDER BY col DESC)   -- same rank for equal values; use for tied rankings
LAG(col, 1) OVER (ORDER BY date)
LEAD(col, 1) OVER (ORDER BY date)
SUM(col) OVER (PARTITION BY g ORDER BY date ROWS UNBOUNDED PRECEDING)
```

`QUALIFY` clause filters on window function results without a subquery:
```sql
SELECT * FROM table
QUALIFY DENSE_RANK() OVER (ORDER BY metric DESC) <= 10
```

Use `DENSE_RANK()` for rankings where ties should share the same rank. Use `ROW_NUMBER()` only when you explicitly need no ties.

## 8. UNPIVOT / PIVOT

```sql
-- UNPIVOT: columns to rows
UNPIVOT table ON col1, col2 INTO NAME category VALUE val

-- PIVOT: rows to columns
PIVOT table ON category USING SUM(val)
```

## 9. Conditional Expressions

```sql
CASE WHEN condition THEN result ELSE default END
COALESCE(a, b, c)               -- first non-NULL
NULLIF(a, b)                    -- NULL if a = b
IF(condition, true_val, false_val)
```

## 10. SCD Type 2 Patterns

```sql
-- First value per entity (original):
FIRST_VALUE(col) OVER (PARTITION BY entity ORDER BY valid_from ASC)

-- Current record:
WHERE valid_to IS NULL

-- Most recent record via ROW_NUMBER:
ROW_NUMBER() OVER (PARTITION BY entity ORDER BY valid_from DESC) AS rn
-- then WHERE rn = 1
```

## 11. MRR Change Category

The LAG-based pattern structure is correct. String literals vary per project — always read `.md` files in `models/` for exact strings. Look for `{% docs change_category %}` blocks; they contain a table showing exactly which strings to use.

```sql
WITH mrr AS (
    SELECT customer_id, month, mrr,
        LAG(mrr, 1) OVER (PARTITION BY customer_id ORDER BY month) AS prev_mrr
    FROM {{ ref('stg_mrr') }}
)
SELECT customer_id, month, mrr,
    CASE
        WHEN prev_mrr IS NULL AND mrr > 0             THEN 'new'
        WHEN prev_mrr = 0     AND mrr > 0             THEN 'reactivation'
        WHEN mrr > prev_mrr   AND prev_mrr IS NOT NULL THEN '<check project .md docs>'
        WHEN mrr < prev_mrr   AND mrr > 0             THEN '<check project .md docs>'
        WHEN mrr = 0          AND prev_mrr > 0        THEN 'churn'
        WHEN mrr = prev_mrr                           THEN 'no_change'
        ELSE 'other'
    END AS change_category
FROM mrr
```
