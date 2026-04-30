---
name: sqlite-sql
description: "SQLite-specific SQL patterns: substr/instr for string ops, || for concatenation, LIKE (no ILIKE), date()/strftime() for dates, CAST for type coercion, no FULL OUTER JOIN, GROUP_CONCAT, typeof(), COALESCE/IFNULL, printf() formatting."
type: skill
---

# SQLite SQL Skill

## 1. String Functions — substr() and instr()

SQLite has no `POSITION()` or `SPLIT_PART()`. Use `substr()` and `instr()`:

```sql
-- Extract substring starting at position 3, length 5
SELECT substr(col, 3, 5) FROM t;

-- Find position of substring (0 if not found)
SELECT instr(col, 'needle') FROM t;

-- Extract everything after a delimiter
SELECT substr(col, instr(col, '/') + 1) FROM t
WHERE instr(col, '/') > 0;
```

## 2. String Concatenation — Use || (not CONCAT)

```sql
-- Concatenate two strings
SELECT first_name || ' ' || last_name AS full_name FROM employees;

-- With NULL handling (|| propagates NULL)
SELECT COALESCE(first_name, '') || ' ' || COALESCE(last_name, '') AS full_name
FROM employees;
```

## 3. Case-Insensitive Matching — LIKE Only (no ILIKE)

SQLite's LIKE is case-insensitive for ASCII letters by default. There is no `ILIKE`:

```sql
-- Case-insensitive search (ASCII only by default)
WHERE name LIKE '%widget%'

-- For Unicode/non-ASCII, use UPPER/LOWER explicitly
WHERE UPPER(name) LIKE UPPER('%widget%')
```

## 4. Date Functions — date(), datetime(), strftime()

SQLite stores dates as text (ISO 8601), real, or integer. Use built-in date functions:

```sql
-- Current date / datetime
SELECT date('now');
SELECT datetime('now');

-- Add/subtract time
SELECT date('now', '+7 days');
SELECT date('now', '-1 month');
SELECT date(col, '+1 year') FROM t;

-- Truncate to month start
SELECT date(col, 'start of month') FROM t;

-- Extract parts
SELECT strftime('%Y', col) AS year FROM t;
SELECT strftime('%m', col) AS month FROM t;
SELECT strftime('%Y-%m', col) AS year_month FROM t;

-- Difference in days (days between two dates)
SELECT CAST(julianday(end_date) - julianday(start_date) AS INTEGER) AS days_diff
FROM t;
```

## 5. Type Coercion — CAST() Only (no :: syntax)

SQLite does not support the `::` cast syntax. Use `CAST()`:

```sql
-- Cast to integer
SELECT CAST(price AS INTEGER) FROM products;

-- Cast to real
SELECT CAST(score AS REAL) FROM results;

-- Cast to text
SELECT CAST(id AS TEXT) FROM records;
```

## 6. No FULL OUTER JOIN — Simulate with UNION

SQLite does not support FULL OUTER JOIN. Simulate it:

```sql
-- FULL OUTER JOIN equivalent
SELECT a.id, a.val, b.val
FROM table_a a
LEFT JOIN table_b b ON a.id = b.id
UNION
SELECT b.id, a.val, b.val
FROM table_b b
LEFT JOIN table_a a ON b.id = a.id
WHERE a.id IS NULL;
```

## 7. String Aggregation — GROUP_CONCAT

```sql
-- Comma-separated list of values per group
SELECT department, GROUP_CONCAT(name) AS members
FROM employees
GROUP BY department;

-- Custom separator
SELECT department, GROUP_CONCAT(name, ' | ') AS members
FROM employees
GROUP BY department;

-- With ordering (SQLite 3.44+, use subquery for older versions)
SELECT department,
       GROUP_CONCAT(name ORDER BY name) AS sorted_members
FROM employees
GROUP BY department;
```

## 8. Runtime Type Checking — typeof()

```sql
-- Returns 'integer', 'real', 'text', 'blob', or 'null'
SELECT typeof(col) FROM t;

-- Filter by storage class
SELECT * FROM t WHERE typeof(col) = 'integer';
```

## 9. NULL Handling — COALESCE, IFNULL, NULLIF

```sql
-- COALESCE: first non-NULL value
SELECT COALESCE(col1, col2, 'default') FROM t;

-- IFNULL: SQLite shorthand for two-argument COALESCE
SELECT IFNULL(col, 0) FROM t;

-- NULLIF: return NULL if two values are equal
SELECT NULLIF(col, 0) FROM t;   -- returns NULL when col = 0
```

## 10. Formatted Output — printf()

```sql
-- Zero-padded integer
SELECT printf('%05d', id) FROM t;

-- Fixed decimal places
SELECT printf('%.2f', price) FROM t;

-- String formatting
SELECT printf('%s-%s', category, subcategory) FROM t;
```

## 11. Common Anti-Patterns to Avoid

- No `BOOLEAN` type — use `0` and `1` (integers)
- No `ALTER COLUMN` — SQLite only supports `ADD COLUMN` in `ALTER TABLE`
- Prefer `WITHOUT ROWID` only for tables with non-integer primary keys
- Do NOT use `AUTOINCREMENT` unless you need gap-free IDs — plain `INTEGER PRIMARY KEY` gives auto-increment behavior and is faster
- `LIKE` pattern uses `%` (any chars) and `_` (one char) — no regex by default
- `IN (SELECT ...)` is generally faster than correlated subqueries in SQLite
- Do NOT use `= NULL` — use `IS NULL`
- `||` propagates NULL — wrap with `COALESCE` when concatenating nullable columns

## 12. Benchmark Patterns

- **Window functions**: SQLite supports ROW_NUMBER, RANK, DENSE_RANK, NTILE, LAG, LEAD since 3.25. No QUALIFY — use subquery wrapping.
- **HAVING without GROUP BY**: Not valid in SQLite — always pair HAVING with GROUP BY.
- **Recursive CTEs**: `WITH RECURSIVE` works in SQLite — useful for hierarchical data (org charts, category trees).
- **No LIMIT in subqueries with IN**: `WHERE col IN (SELECT ... LIMIT N)` is not supported — use a CTE instead.
