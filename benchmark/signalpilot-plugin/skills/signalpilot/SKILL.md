---
name: signalpilot
description: "BLOCKING REQUIREMENT: If the user's message mentions dbt, SQL, database, or data pipeline - invoke this skill as your FIRST tool call, BEFORE Read, Glob, Grep, Bash, or Agent. Covers: SignalPilot MCP tools, available skills, and the governed workflow for dbt projects, SQL queries, schema discovery, and database access."
---

# SignalPilot - Governed AI Database Access

## MCP Tools
The SignalPilot MCP provides governed database access:
- `query_database` - governed read-only SQL execution
- `validate_sql` / `explain_query` / `estimate_query_cost` - pre-execution checks
- `schema_overview` / `schema_ddl` / `schema_link` - schema discovery
- `describe_table` / `explore_table` / `explore_columns` / `explore_column` - deep dives
- `list_tables` / `get_relationships` / `find_join_path` - structure and joins
- `compare_join_types` - JOIN impact analysis
- `get_date_boundaries` - date ranges across all tables
- `check_model_schema` / `validate_model_output` / `audit_model_sources` - dbt validation
- `analyze_grain` - cardinality and grain analysis
- `debug_cte_query` - step-through CTE debugging
- `dbt_error_parser` - parse dbt error output into structured info
- `list_projects` / `get_project` - dbt project management
- `check_budget` / `connection_health` / `query_history` - operational

## Local Scripts (via plugin)
For local dbt project work, use these standalone scripts:
- `scan_project.py` - scan a dbt project: models, stubs, deps, hazards, work order
- `validate_project.py` - run `dbt parse` and report structural errors

Use `ToolSearch` to discover additional tools as needed.

## Available Skills
Load these skills as needed for specialized work:

### dbt Projects
- `/signalpilot-dbt:dbt-workflow` - Load FIRST for any dbt project. Full 7-step
  workflow: scan, map, validate, write, verify.
- `/signalpilot-dbt:dbt-write` - Loaded at Step 2 for writing and verifying SQL models
- `/signalpilot-dbt:dbt-debugging` - Load when dbt run/parse fails

### SQL (load the one matching your database)
- `/signalpilot-dbt:duckdb-sql` - DuckDB-specific syntax and gotchas
- `/signalpilot-dbt:snowflake-sql` - Snowflake-specific patterns
- `/signalpilot-dbt:bigquery-sql` - BigQuery-specific patterns
- `/signalpilot-dbt:sqlite-sql` - SQLite-specific patterns

### General SQL
- `/signalpilot-dbt:sql-workflow` - Structured query building and verification

## Quick Start

**For dbt projects:** Load `/signalpilot-dbt:dbt-workflow` - it orchestrates the
full lifecycle including scanning, mapping, writing, and verification.

**For SQL queries:** Load `/signalpilot-dbt:sql-workflow` + the SQL skill for your
database engine.

**For schema exploration:** Use the MCP tools directly - `schema_overview` for a
broad view, `describe_table` for column details, `explore_table` for sample data.
