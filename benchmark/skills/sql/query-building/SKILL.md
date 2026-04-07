---
description: "SQL query building strategies — schema exploration, multi-table joins, CTEs, subqueries, and result validation."
---

# SQL Query Building

## Schema Exploration Strategy
1. List all tables to understand scope
2. For each relevant table, check column names and types
3. Look for foreign key relationships between tables
4. Sample a few rows from key tables to understand data formats
5. Identify join columns even without explicit FKs (naming conventions like `_id` suffix)

## Building Complex Queries
1. Break the question into sub-questions
2. Write and test each sub-query independently
3. Use CTEs (`WITH` clauses) for readability and debugging
4. Verify join conditions produce expected row counts
5. Check for NULL handling in join columns
6. Use DISTINCT when joins might produce duplicates

## CTE Pattern
```sql
WITH customers AS (
    SELECT * FROM {{ ref('stg_customer') }}
),
orders AS (
    SELECT * FROM {{ ref('stg_order') }}
    WHERE status = 'completed'
),
summary AS (
    SELECT
        c.customer_id,
        c.name,
        COUNT(o.order_id) AS total_orders,
        SUM(o.amount) AS total_spent
    FROM customers c
    LEFT JOIN orders o ON c.customer_id = o.customer_id
    GROUP BY 1, 2
)
SELECT * FROM summary
```

## Result Validation
After getting query results:
1. Does the number of columns match what's expected?
2. Do the values make sense for the domain?
3. Are numeric results in the right order of magnitude?
4. Check edge cases: empty results, NULL values, duplicate rows
5. If counting, verify against a simpler `COUNT(*)` query

## Common Pitfalls
- Forgetting GROUP BY for non-aggregated columns
- Using INNER JOIN when LEFT JOIN is needed (dropping unmatched rows)
- Not handling NULLs in aggregation (`SUM(NULL)` = `NULL`, not 0)
- Wrong column in ORDER BY when using positional references
- Comparing strings with different case — use `LOWER()` or `UPPER()`
