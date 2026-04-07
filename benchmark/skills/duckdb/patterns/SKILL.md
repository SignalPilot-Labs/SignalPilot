---
description: "DuckDB core SQL patterns — string functions, aggregation, window functions, type casting, and common gotchas."
---

# DuckDB SQL Patterns

## String Functions
```sql
CONCAT(a, ' ', b)          -- or a || ' ' || b
LENGTH(s)
LOWER(s), UPPER(s)
TRIM(s), LTRIM(s), RTRIM(s)
REPLACE(s, 'old', 'new')
SUBSTRING(s, start, len)
REGEXP_MATCHES(s, pattern)  -- returns bool
LIST_STRING_AGG(col)        -- aggregate strings
STRING_AGG(col, ', ')       -- with separator
```

## Aggregation
```sql
COUNT(*), COUNT(DISTINCT col)
SUM(col), AVG(col), MIN(col), MAX(col)
MEDIAN(col), QUANTILE_CONT(col, 0.95)
LIST(col)                   -- collect into list
ARRAY_AGG(col)              -- same as LIST
FIRST(col), LAST(col)       -- first/last in group
```

## Window Functions
```sql
ROW_NUMBER() OVER (PARTITION BY g ORDER BY o)
RANK() OVER (ORDER BY col DESC)
LAG(col, 1) OVER (ORDER BY date)
LEAD(col, 1) OVER (ORDER BY date)
SUM(col) OVER (PARTITION BY g ORDER BY date ROWS UNBOUNDED PRECEDING)
```

## Type Casting
```sql
CAST(x AS INTEGER)
CAST(x AS DOUBLE)
CAST(x AS VARCHAR)
CAST(x AS DATE)
CAST(x AS TIMESTAMP)
TRY_CAST(x AS INTEGER)     -- returns NULL on failure
```

## UNION / Set Operations
```sql
SELECT * FROM a UNION ALL SELECT * FROM b  -- keep duplicates (faster)
SELECT * FROM a UNION SELECT * FROM b      -- remove duplicates
SELECT * FROM a INTERSECT SELECT * FROM b
SELECT * FROM a EXCEPT SELECT * FROM b
```

## UNPIVOT / PIVOT
```sql
-- UNPIVOT: columns to rows
UNPIVOT table ON col1, col2, col3 INTO NAME category VALUE amount

-- PIVOT: rows to columns
PIVOT table ON category USING SUM(amount)
```

## Conditional / CASE
```sql
CASE WHEN condition THEN result ELSE default END
COALESCE(a, b, c)           -- first non-NULL
NULLIF(a, b)                -- NULL if a = b
IF(condition, true_val, false_val)  -- DuckDB extension
```

## Join Patterns (avoid row count bugs)
```sql
-- LEFT JOIN preserves all rows from left table
-- INNER JOIN can reduce rows — check if that's intended
-- Multiple matches in right table MULTIPLY rows — use DISTINCT or GROUP BY
-- To avoid duplication, ensure join keys are unique in the right table:
SELECT * FROM orders o
LEFT JOIN (SELECT customer_id, MAX(name) as name FROM customers GROUP BY 1) c
  ON o.customer_id = c.customer_id

-- CROSS JOIN for date spines:
SELECT d.date, t.team_id FROM date_spine d CROSS JOIN teams t
```

## Common Gotchas
- Integer division: `5/2 = 2` — use `5.0/2` or `CAST(5 AS DOUBLE)/2`
- `NULL` comparisons: use `IS NULL` / `IS NOT NULL`, never `= NULL`
- `BOOLEAN` type exists: `TRUE`, `FALSE`
- Lists are first-class: `[1, 2, 3]`, `LIST_VALUE(1, 2, 3)`
- Structs: `{'key': 'value'}`, `ROW(1, 'a')`
- No `ILIKE` with `_` wildcard quirks — `_` matches any single char
- Column names are case-insensitive but **alias names preserve case**: use `LOWER()` column aliases to match YML specs
- Use `COLUMNS(*)` to select all columns; `EXCLUDE` to drop: `SELECT * EXCLUDE (col1, col2) FROM t`
- `COALESCE(col, 0)` for NULL-to-zero, `COALESCE(col, '')` for NULL-to-empty-string
