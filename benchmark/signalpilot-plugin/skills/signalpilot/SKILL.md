---
name: signalpilot
description: "SignalPilot MCP tool catalog for governed database access."
disable-model-invocation: true
---

# SignalPilot Database Access

## MCP Tools

- `query_database` — run governed read-only SQL
- `validate_sql` / `explain_query` / `estimate_query_cost` — inspect SQL before execution
- `schema_overview` / `schema_ddl` / `schema_link` — discover schema
- `describe_table` / `explore_table` / `explore_columns` / `explore_column` — inspect relations and values
- `list_tables` / `get_relationships` / `find_join_path` — inspect structure and joins
- `compare_join_types` — measure JOIN populations
- `get_date_boundaries` — inspect date ranges
- `check_model_schema` / `validate_model_output` / `audit_model_sources` / `verify_model_values` — inspect dbt outputs
- `analyze_grain` — measure grain and cardinality
- `debug_cte_query` / `dbt_error_parser` — diagnose SQL and dbt errors
- `connection_health` / `query_history` — inspect connection state

## Local Scripts

- `scan_project.py` — inspect dbt project structure and hazards
- `validate_project.py` — run `dbt parse` and report structural errors

Use `ToolSearch` to discover additional tools because the available catalog can vary by deployment.
