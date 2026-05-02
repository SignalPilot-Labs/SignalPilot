---
name: snowflake-sql
description: "Snowflake-specific SQL patterns: QUALIFY for window filtering, LATERAL FLATTEN for arrays, semi-structured VARIANT data, ILIKE for case-insensitive matching, date functions, and time travel."
type: skill
---

# Snowflake SQL Skill

## 1. Window Function Filtering — Use QUALIFY

Instead of wrapping in a subquery, use QUALIFY:

```sql
-- Find the latest record per customer
SELECT customer_id, order_date, amount
FROM orders
QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC) = 1;

-- Top 5 products by sales
SELECT product_id, total_sales
FROM sales_summary
QUALIFY DENSE_RANK() OVER (ORDER BY total_sales DESC) <= 5;
```

## 2. Case-Insensitive Matching — Use ILIKE

```sql
-- Case-insensitive LIKE
WHERE product_name ILIKE '%widget%'

-- Case-insensitive equality
WHERE UPPER(status) = 'ACTIVE'
-- or
WHERE status ILIKE 'active'
```

## 3. Arrays and Semi-Structured Data — LATERAL FLATTEN

```sql
-- Explode an ARRAY column
SELECT t.id, f.value AS item
FROM table t,
LATERAL FLATTEN(input => t.array_col) f;

-- Access VARIANT fields
SELECT col:field_name::STRING AS field_value
FROM table;

-- Parse JSON string
SELECT PARSE_JSON(json_col):key::STRING AS val
FROM table;
```

## 4. Date Functions

```sql
-- Add/subtract time
DATEADD(day, 7, order_date)          -- 7 days from order_date
DATEADD(month, -1, current_date())   -- 1 month ago

-- Difference between dates
DATEDIFF(day, start_date, end_date)  -- days between dates
DATEDIFF(month, start_date, end_date)

-- Truncate to period
DATE_TRUNC('month', event_ts)
DATE_TRUNC('year', event_ts)

-- Current timestamp
CURRENT_TIMESTAMP()
CURRENT_DATE()
```

## 5. String Functions

```sql
SPLIT_PART(col, '/', 1)              -- split by delimiter, get Nth part
REGEXP_SUBSTR(col, '[0-9]+')         -- first match of regex
TRIM(col)                            -- remove leading/trailing whitespace
LTRIM(col, '0')                      -- remove leading zeros
UPPER(col) / LOWER(col)
CONCAT(col1, '-', col2)              -- or col1 || '-' || col2
```

## 6. Null-Safe Equality

```sql
-- NULL-safe: TRUE when both are NULL or both equal
col1 IS NOT DISTINCT FROM col2

-- COALESCE for default values
COALESCE(col, 'unknown')
```

## 7. Time Travel (querying historical data)

```sql
-- Query table as it was 1 hour ago
SELECT * FROM my_table AT (OFFSET => -3600);

-- Query at a specific timestamp
SELECT * FROM my_table AT (TIMESTAMP => '2024-01-01'::TIMESTAMP);
```

## 8. Common Anti-Patterns to Avoid

- Do NOT use `= NULL` — use `IS NULL`
- Do NOT use `<>` for NULL comparison — use `IS NOT NULL`
- Prefer `QUALIFY` over subquery wrapping for window filters
- When accessing VARIANT fields, always cast: `col:field::STRING`

## 9. Benchmark Patterns

- **Numeric precision**: Snowflake returns DECIMAL/NUMBER with configurable precision. Do NOT cast to FLOAT unless needed — precision loss fails exact-match evaluation.
- **IDENTIFIER case**: Snowflake upper-cases identifiers by default. Use double-quotes `"lower_case_col"` when column names are lowercase in source. Always check with `describe_table`.
- **LISTAGG**: Use `LISTAGG(col, ',') WITHIN GROUP (ORDER BY col)` for string aggregation (not GROUP_CONCAT).
- **TRY_CAST / TRY_TO_NUMBER**: Use for safe type conversion that returns NULL instead of error.
- **OBJECT_KEYS / ARRAY_SIZE**: Useful for introspecting semi-structured data before querying.

## 10. Convention Gotchas

These are Snowflake defaults that have silently produced wrong values in
past runs. Probe a sample row and verify before committing.

### Don't wrap raw values in transformations
- A column stored as a raw integer (e.g., a microsecond epoch) or an
  opaque code should flow through unchanged unless the question explicitly
  asks for date/string output. Wrapping with `TO_DATE(TO_TIMESTAMP(col))`
  silently converts a numeric to a date and breaks value-vector matching.
  Return raw values by default.

### Date arithmetic — argument order
- `DATEDIFF(unit, start, end)` — note the unit is FIRST in Snowflake, opposite
  of BigQuery's `DATE_DIFF(end, start, unit)`. Months between Jan-15 and Mar-15:
  `DATEDIFF(MONTH, '2024-01-15', '2024-03-15')` = 2. As with BigQuery, this
  counts boundaries crossed, not active months — gold may expect +1 if
  counting both endpoint months.

### Calendar conventions
- `DATE_TRUNC('WEEK', date)` truncates to **Monday-start** weeks (ISO),
  unlike BigQuery's Sunday-start default. If the question implies a
  different week-start, use `DATE_TRUNC('DAY', date)` and a custom offset.
- `DAYOFWEEK(date)` returns **0=Sunday, 6=Saturday** (configurable via
  `WEEK_START` session parameter — assume default unless told otherwise).
  `DAYOFWEEKISO(date)` returns 1=Monday, 7=Sunday.

### NULL ordering
- Default `ORDER BY col ASC` puts **NULLS LAST**; `ORDER BY col DESC` puts
  **NULLS FIRST**. If gold expects the opposite (e.g., a min-aggregation
  ranking that should put NULLs at top of a DESC sort), specify
  `NULLS LAST` / `NULLS FIRST` explicitly.

### Percentile / median
- `PERCENTILE_CONT(0.5)` interpolates linearly between two values when the
  median lands between rows; `PERCENTILE_DISC(0.5)` returns the lower
  ranked value. Different functions for different gold conventions.
  Verify which one the question expects.

### LATERAL FLATTEN granularity
- Each row from `LATERAL FLATTEN(input => col)` multiplies the parent row,
  producing one output per array element. If the question asks for a
  per-parent aggregate, you must `GROUP BY` the parent key after FLATTEN,
  or flatten only inside a subquery before re-aggregating.

### Sample vs full tables
- Some Snowflake-port datasets (e.g., `PATENTSVIEW`) contain `SAMPLE_*`
  test tables alongside full production tables. Always use the full
  table unless the question explicitly says "sample" — `SAMPLE_USPC` etc.
  produce wrong row counts and miss values.

### Identifier case
- Snowflake upper-cases identifiers by default. Source tables ported from
  BigQuery often have lowercase column names; access these with
  double-quotes: `"lower_case_col"`. `describe_table` reveals the actual
  storage case.
