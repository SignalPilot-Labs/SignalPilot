---
name: duckdb-sql
description: "Load when hitting DuckDB syntax errors or writing DuckDB-specific SQL. Covers gotchas that differ from PostgreSQL/MySQL."
type: skill
---

# DuckDB SQL — Key Differences from PostgreSQL/MySQL

## Gotchas

- **Integer division truncates**: `5/2 = 2`. Fix: `CAST(numerator AS DOUBLE) / denominator`
- **DATE_TRUNC returns TIMESTAMP**: Cast result if DATE needed: `CAST(DATE_TRUNC('month', col) AS DATE)`
- **INTERVAL syntax**: `INTERVAL '1' DAY` (quoted), NOT `INTERVAL 1 DAY`
- **No DATEADD/DATEDIFF**: Use `col + INTERVAL '1' DAY` and `DATE_DIFF('day', start, end)`
- **SUM(NULL) = NULL**: Not 0. Use `COALESCE(SUM(col), 0)` if 0 is needed.
- **ROUND precision**: If the YML specifies a decimal type like `decimal(6,2)`,
  cast the FINAL output to match: `CAST(ROUND(AVG(col), 2) AS DECIMAL(6,2))`.
  Do NOT cast the input — cast the result after rounding.
- **Avoid CURRENT_DATE** in models with historical data — use `(SELECT MAX(date_col) FROM source)` to anchor to the data's actual date range

## Date Parsing

- Non-ISO strings: `STRPTIME(col, '%d/%m/%Y')::DATE`
- `TRY_STRPTIME` returns NULL on failure (safe)
- Never `CAST(date_str AS DATE)` on non-ISO strings

## QUALIFY Clause

Filter window function results without a subquery:
```sql
SELECT *, ROW_NUMBER() OVER (PARTITION BY group ORDER BY col DESC) AS rn
FROM table
QUALIFY rn <= 10
```

## Date Spines

```sql
SELECT UNNEST(GENERATE_SERIES(min_date::DATE, max_date::DATE, INTERVAL '1' DAY)) AS date_day
```
Always use the primary fact table's max date as endpoint — call `get_date_boundaries` first.

## Type Casting

`CAST(x AS INTEGER)`, `CAST(x AS DOUBLE)`, `CAST(x AS VARCHAR)`, `CAST(x AS DATE)`
`TRY_CAST` returns NULL on failure.
