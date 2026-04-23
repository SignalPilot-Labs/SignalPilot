---
name: signalpilot
description: "BLOCKING REQUIREMENT: If the user's message mentions dbt, SQL, database, or data pipeline — invoke this skill as your FIRST tool call, BEFORE Read, Glob, Grep, Bash, or Agent. Covers: SignalPilot MCP tools, available skills, and the governed workflow for dbt projects, SQL queries, schema discovery, and database access."
---

# SignalPilot — Governed AI Database Access

## Tools
The SignalPilot MCP provides database access and data-aware tools:
- `query_database` — governed read-only SQL execution
- `dbt_project_map` — project overview: model status, column contracts, build order
- `dbt_project_validate` — run `dbt parse` and return structured errors
- `check_model_schema` — compare actual columns vs YML contract
- `validate_model_output` — row count + basic checks
- `get_date_boundaries` — date ranges across all tables
- `schema_overview` / `describe_table` / `explore_table` — schema discovery
- `find_join_path` / `compare_join_types` — relationship analysis
- `debug_cte_query` — debugging utilities

Use `ToolSearch` to discover additional tools as needed.

## Available Skills
Load these skills as needed for specialized work:

### dbt Projects
- `/signalpilot-dbt:dbt-workflow` — Load FIRST for any dbt project. Full 5-step
  workflow: scan, map, validate, write, verify.
- `/signalpilot-dbt:dbt-write` — Load at Step 4 when writing SQL models
- `/signalpilot-dbt:dbt-debugging` — Load when dbt run/parse fails
- `/signalpilot-dbt:dbt-date-spines` — Load to fix current_date/now() hazards

### SQL (load the one matching your database)
- `/signalpilot-dbt:duckdb-sql` — DuckDB-specific syntax and gotchas
- `/signalpilot-dbt:snowflake-sql` — Snowflake-specific patterns
- `/signalpilot-dbt:bigquery-sql` — BigQuery-specific patterns
- `/signalpilot-dbt:sqlite-sql` — SQLite-specific patterns

### General SQL
- `/signalpilot-dbt:sql-workflow` — Structured query building and verification

## Quick Start

**For dbt projects:** Load `/signalpilot-dbt:dbt-workflow` — it orchestrates the
full lifecycle including scanning, mapping, writing, and verification.

**For SQL queries:** Load `/signalpilot-dbt:sql-workflow` + the SQL skill for your
database engine.

**For schema exploration:** Use the MCP tools directly — `schema_overview` for a
broad view, `describe_table` for column details, `explore_table` for sample data.
