# SQL Benchmark System Prompt — Snowflake

This file is for documentation and reference only. The actual agent prompt
is built programmatically by `benchmark/agent/sql_prompts.py`.

---

## Overview

For spider2-snowflake tasks, the agent receives a SQL question and must:

1. Explore the Snowflake schema via SignalPilot MCP tools
2. Write a valid Snowflake SQL query
3. Execute it via `mcp__signalpilot__query_database`
4. Save the final SQL to `result.sql`
5. Save the query result as CSV to `result.csv`

## MCP Tools Available

- `mcp__signalpilot__schema_overview` — list all schemas and tables
- `mcp__signalpilot__schema_ddl` — full DDL as CREATE TABLE statements
- `mcp__signalpilot__list_tables` — list tables in a schema
- `mcp__signalpilot__describe_table` — column names, types, constraints
- `mcp__signalpilot__explore_table` — sample rows and statistics
- `mcp__signalpilot__explore_column` — distinct values for a column
- `mcp__signalpilot__query_database` — execute SQL (read-only)
- `mcp__signalpilot__validate_sql` — syntax check without executing
- `mcp__signalpilot__find_join_path` — find how to join two tables

## Snowflake SQL Tips

- **QUALIFY** for window function filtering (avoids subquery wrapping)
- **ILIKE** for case-insensitive string matching
- **LATERAL FLATTEN** for array and semi-structured data expansion
- **DATEADD / DATEDIFF** for date arithmetic
- **VARIANT / OBJECT_CONSTRUCT** for semi-structured columns
- **SPLIT_PART, REGEXP_SUBSTR** for string manipulation
- Null-safe equality: `col IS NOT DISTINCT FROM other_col`

## Output Requirements

- `result.sql` — the final SQL query used to produce the answer
- `result.csv` — the query result with a header row
