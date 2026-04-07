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

## Common Gotchas
- Integer division: `5/2 = 2` — use `5.0/2` or `CAST(5 AS DOUBLE)/2`
- `NULL` comparisons: use `IS NULL` / `IS NOT NULL`, never `= NULL`
- `BOOLEAN` type exists: `TRUE`, `FALSE`
- Lists are first-class: `[1, 2, 3]`, `LIST_VALUE(1, 2, 3)`
- Structs: `{'key': 'value'}`, `ROW(1, 'a')`
- No `ILIKE` with `_` wildcard quirks — `_` matches any single char
