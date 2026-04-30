---
sidebar_position: 2
---

# SQL Exploration Walk-through

Ad-hoc schema discovery and query execution with SignalPilot's exploration tools.

## Schema discovery

Before writing any SQL, understand what's in the database.

### List all tables

```
Tool: list_tables
connection: my-warehouse
→ analytics.orders (48,291 rows, 12 cols, 3 FKs)
→ analytics.customers (8,204 rows, 9 cols, 0 FKs)
→ analytics.products (1,203 rows, 6 cols, 2 FKs)
```

`list_tables` returns a compact one-line-per-table overview: columns, PKs, FKs, row counts. Use it to orient before drilling in.

### Describe a table

```
Tool: describe_table
table: analytics.orders
→ order_id: bigint, NOT NULL, PK
→ customer_id: bigint, NOT NULL, FK → customers.customer_id
→ order_date: date, NOT NULL
→ total_amount: numeric(10,2), nullable
→ status: varchar(20), NOT NULL
```

`describe_table` gives full column detail: types, nullability, PK/FK relationships, any PII flags.

### Explore a categorical column

```
Tool: explore_column
table: analytics.orders
column: status
→ completed:  31,204 (64.7%)
→ pending:     9,182 (19.0%)
→ cancelled:   5,210 (10.8%)
→ refunded:    2,695 (5.6%)
```

`explore_column` shows distinct values with counts and percentages. Essential for understanding filter conditions before writing a WHERE clause.

### Database-wide overview

```
Tool: schema_overview
connection: my-warehouse
→ 12 tables, 312,041 total rows
→ FK density: 2.3 FKs per table
→ Hub tables: orders (most connected), customers
```

`schema_overview` gives a database-wide summary — useful for orienting in an unfamiliar schema.

## Join path discovery

If you know two tables but don't know how to join them:

```
Tool: find_join_path
from: analytics.orders
to: analytics.products
→ orders → order_items (via order_id)
→ order_items → products (via product_id)
```

`find_join_path` uses FK relationships to find join paths up to 6 hops. Eliminates guesswork on unfamiliar schemas.

To understand what join type gives the right row count:

```
Tool: compare_join_types
left: analytics.orders
right: analytics.customers
on: customer_id
→ INNER JOIN: 48,000 rows
→ LEFT JOIN:  48,291 rows (291 orders have no customer record)
→ RIGHT JOIN: 48,291 rows (same as LEFT)
```

## Cost-aware querying

Before running an expensive query on BigQuery or Snowflake:

```
Tool: estimate_query_cost
sql: SELECT * FROM analytics.large_events WHERE event_date > '2024-01-01'
→ estimated_cost: $1.24
→ bytes_processed: 4.8 GB
→ recommendation: Add a partition filter on event_date to reduce cost
```

If the cost is acceptable, run it:

```
Tool: query_database
sql: SELECT * FROM analytics.large_events WHERE event_date > '2024-01-01'
→ [returns first 1000 rows — LIMIT auto-injected]
```

## Multi-column statistics

For data profiling across multiple columns at once:

```
Tool: explore_columns
table: analytics.orders
columns: [total_amount, quantity, discount_pct]
→ total_amount: min=0.00, max=12,400.00, avg=182.30, 3 NULLs
→ quantity: min=1, max=50, avg=2.3, 0 NULLs
→ discount_pct: min=0.0, max=100.0, avg=8.2, 412 NULLs
```

## Debug a CTE step by step

For complex queries, validate each CTE independently:

```
Tool: debug_cte_query
sql: |
  WITH base AS (SELECT ... FROM orders WHERE ...),
  joined AS (SELECT ... FROM base LEFT JOIN customers ...)
  SELECT ... FROM joined
→ CTE 'base': valid, 48,291 rows
→ CTE 'joined': valid, 48,291 rows (no fan-out)
→ Final SELECT: valid
```

## Cross-links

- [`list_tables`](/docs/reference/tools-schema#list_tables) — table overview
- [`describe_table`](/docs/reference/tools-schema#describe_table) — column detail
- [`explore_column`](/docs/reference/tools-schema#explore_column) — distinct values
- [`find_join_path`](/docs/reference/tools-query#find_join_path) — FK-based join discovery
- [`estimate_query_cost`](/docs/reference/tools-query#estimate_query_cost) — pre-run cost check
- [`query_database`](/docs/reference/tools-query#query_database) — governed SQL execution
