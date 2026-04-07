---
name: signalpilot_data_tools
description: "How to use SignalPilot MCP tools for database exploration, schema discovery, and query execution in benchmark tasks."
type: skill
priority: 9
---

# SignalPilot Data Tools

You have access to SignalPilot's MCP server for governed database access. Use these tools instead of raw SQL when exploring databases.

## Available Tools

### Schema Discovery (use these FIRST)
- **`list_database_connections`** — See all registered databases
- **`list_tables`** — List all tables with compact schema overview
- **`describe_table`** — Column names, types, and constraints for a table
- **`explore_table`** — Deep-dive: columns, types, FK refs, sample values
- **`schema_overview`** — Quick DB overview: table count, columns, rows, FK density
- **`schema_link`** — Find tables relevant to a natural language question (smart matching)
- **`find_join_path`** — Find how to join two tables (follows FK chains)
- **`get_relationships`** — All foreign key relationships (ERD overview)

### Query Execution
- **`query_database`** — Execute governed, read-only SQL. Parameters: `connection_name`, `sql`, `row_limit`
- **`validate_sql`** — Check SQL syntax without running it
- **`explain_query`** — Get execution plan without running

### Code Execution
- **`execute_code`** — Run Python in an isolated sandbox (for data processing)

## Exploration Strategy

For dbt tasks:
1. `list_database_connections` — confirm the DuckDB is registered
2. `list_tables` — see raw source tables
3. `explore_table` on key tables — understand columns and relationships
4. `query_database` to sample data and test SQL fragments
5. Use what you learn to write the dbt model SQL files

For text-to-SQL tasks:
1. `schema_link` with the question — find relevant tables automatically
2. `describe_table` on matched tables — get exact column names
3. `find_join_path` between tables you need to join
4. `query_database` to execute your SQL

## Connection Names
- DuckDB files are registered with a connection name matching the task (e.g., `chinook001`)
- Use `list_database_connections` if unsure of the name
