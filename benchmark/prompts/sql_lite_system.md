# SQL Benchmark System Prompt — Spider2-Lite (SQLite / BigQuery / Snowflake)

This file is for documentation and reference only. The actual agent prompt
is built programmatically by `benchmark/agent/sql_prompts.py`.

---

## Overview

Spider2-lite tasks cover three database backends:
- **SQLite** — local file-based database copied into the workdir
- **BigQuery** — Google BigQuery project/dataset
- **Snowflake** — Snowflake database/schema

The runner detects the backend from the task's `type` field and
builds the appropriate prompt with backend-specific tips.

For all lite tasks, the agent must:

1. Explore the schema via SignalPilot MCP tools
2. Write a SQL query in the backend's dialect
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

## Backend-Specific Tips

### SQLite
- String concatenation: `||` operator (not CONCAT)
- Substring: `substr(col, start, length)` — 1-indexed
- Find position: `instr(haystack, needle)`
- LIKE is case-insensitive for ASCII by default
- No FULL OUTER JOIN — simulate with UNION of LEFT JOINs
- Date functions: `date()`, `datetime()`, `strftime()`

### BigQuery
- UNNEST for array expansion
- DATE_DIFF / DATE_ADD / DATE_TRUNC for date arithmetic
- Table references: `` `project.dataset.table` `` (backtick-quoted)
- SELECT * EXCEPT (col) or SELECT * REPLACE (expr AS col)
- ARRAY_AGG, STRUCT for complex types

### Snowflake
- QUALIFY for window function filtering
- ILIKE for case-insensitive string matching
- LATERAL FLATTEN for arrays and semi-structured data
- DATEADD / DATEDIFF for date arithmetic

## Output Requirements

- `result.sql` — the final SQL query used to produce the answer
- `result.csv` — the query result with a header row
