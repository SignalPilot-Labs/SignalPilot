---
name: bigquery-sql
description: "BigQuery-specific SQL patterns: UNNEST for array expansion, STRUCT, ARRAY_AGG, DATE_DIFF/DATE_ADD, backtick-quoted table references, EXCEPT/REPLACE in SELECT, approximate aggregation, partitioned and wildcard tables."
type: skill
---

# BigQuery SQL Skill

## 1. Table References — Always Backtick-Quote

```sql
-- Full table reference
SELECT * FROM `project.dataset.table`;

-- Can omit project if using the default project
SELECT * FROM `dataset.table`;
```

## 2. Array Expansion — Use UNNEST

```sql
-- Explode an array column to rows
SELECT id, item
FROM `project.dataset.table`,
UNNEST(array_col) AS item;

-- UNNEST with offset (position)
SELECT id, item, pos
FROM `project.dataset.table`,
UNNEST(array_col) AS item WITH OFFSET AS pos;

-- UNNEST a literal array
SELECT * FROM UNNEST([1, 2, 3]) AS num;
```

## 3. Date Functions

```sql
-- Add/subtract time
DATE_ADD(order_date, INTERVAL 7 DAY)
DATE_ADD(CURRENT_DATE(), INTERVAL -1 MONTH)

-- Difference between dates
DATE_DIFF(end_date, start_date, DAY)
DATE_DIFF(end_date, start_date, MONTH)

-- Truncate to period
DATE_TRUNC(event_date, MONTH)
TIMESTAMP_TRUNC(event_ts, HOUR)

-- Current date/time
CURRENT_DATE()
CURRENT_TIMESTAMP()
```

## 4. SELECT EXCEPT and REPLACE

```sql
-- All columns except one
SELECT * EXCEPT (col_to_remove) FROM `dataset.table`;

-- Replace a column value inline
SELECT * REPLACE (UPPER(name) AS name) FROM `dataset.table`;
```

## 5. STRUCT and ARRAY_AGG

```sql
-- Create a STRUCT
SELECT STRUCT(id, name) AS person FROM `dataset.table`;

-- Aggregate rows into an array
SELECT department, ARRAY_AGG(employee_name) AS employees
FROM `dataset.employees`
GROUP BY department;

-- Aggregate into array of structs
SELECT ARRAY_AGG(STRUCT(id, name)) AS records FROM `dataset.table`;
```

## 6. Approximate Aggregation (for large tables)

```sql
-- Approximate distinct count (faster for large tables)
APPROX_COUNT_DISTINCT(user_id)

-- Approximate quantiles
APPROX_QUANTILES(value, 100)[OFFSET(50)]  -- median
```

## 7. Partitioned Tables

When querying partitioned tables, always filter on the partition column
to avoid full-table scans:

```sql
-- Partition on _PARTITIONDATE (pseudo-column)
WHERE _PARTITIONDATE >= '2024-01-01'

-- Partition on a date column
WHERE event_date BETWEEN '2024-01-01' AND '2024-12-31'
```

## 8. Wildcard Tables (date-sharded)

```sql
-- Query all date-sharded tables matching a prefix
SELECT * FROM `project.dataset.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20240101' AND '20241231';
```

## 9. String Functions

```sql
REGEXP_EXTRACT(col, r'pattern')          -- extract first match
REGEXP_REPLACE(col, r'pattern', 'repl')  -- replace matches
SPLIT(col, ',')[SAFE_OFFSET(0)]          -- split, access by index
TRIM(col) / LTRIM(col) / RTRIM(col)
FORMAT('%s-%d', str_col, int_col)        -- printf-style formatting
```

## 10. Common Anti-Patterns to Avoid

- Do NOT use `= NULL` — use `IS NULL`
- Do NOT forget to filter partitioned tables — costs money
- Do NOT use `COUNT(DISTINCT ...)` on huge tables — use `APPROX_COUNT_DISTINCT`
- Always backtick-quote table names with dots in them

## 11. Benchmark Patterns

- **STRING_AGG**: Use `STRING_AGG(col, ',' ORDER BY col)` for string aggregation (not GROUP_CONCAT).
- **SAFE_DIVIDE / SAFE_CAST**: Use to avoid division-by-zero errors and cast failures.
- **IF / IIF**: BigQuery supports `IF(condition, true_val, false_val)` — often cleaner than CASE WHEN for simple conditions.
- **GENERATE_DATE_ARRAY / GENERATE_TIMESTAMP_ARRAY**: For date spine generation.
- **Numeric precision**: BigQuery's FLOAT64 can lose precision. Use NUMERIC type or ROUND() only when the question asks for it.
- **INFORMATION_SCHEMA**: `SELECT * FROM dataset.INFORMATION_SCHEMA.COLUMNS` for metadata queries — useful when schema_overview is insufficient.

## 12. Spider2 BigQuery Patterns

- **Default project**: `spider2-public-data`. Table references: `spider2-public-data.{dataset}.{table}`
- **StackOverflow tags**: Stored as pipe-delimited strings in `tags` column (e.g., `|python|python-2.7|`).
  To filter for Python 2 specific questions (excluding Python 3):
  ```sql
  WHERE REGEXP_CONTAINS(tags, r'python-2') AND NOT REGEXP_CONTAINS(tags, r'python-3')
  ```
- **Date columns**: Many BQ tables store dates as TIMESTAMP or DATE. Always check the actual type with describe_table.
- **Large tables**: Use partition filters and LIMIT during exploration. Avoid SELECT * on tables with >1M rows.
