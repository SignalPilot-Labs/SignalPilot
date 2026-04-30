---
sidebar_position: 4
---

# CLAUDE.md Recipes

`CLAUDE.md` is Claude Code's project configuration file. It loads automatically into every session. Use it to pin SignalPilot behavior so you don't repeat yourself.

Place `CLAUDE.md` in your project root (or `~/.claude/CLAUDE.md` for global config).

---

## Template 1 — Small repo / ad-hoc analysis

For a small project with a single database connection and no dbt:

```markdown
# Project config

## Database
Use SignalPilot MCP (signalpilot server) for all database access.
Always call `list_database_connections` at the start of any database session to confirm the active connection.
Default connection: my-postgres

## SQL rules
- Call `validate_sql` before `query_database` for any non-trivial query.
- Use `explore_column` to understand categorical columns before filtering.
- Call `find_join_path` when joining tables you haven't used before.
- Never write SQL without first calling `list_tables` or `describe_table` on the relevant tables.

## Governance
LIMIT is auto-injected by the gateway. Do not add your own LIMIT unless you need fewer rows for a specific reason.
```

---

## Template 2 — dbt repo

For a project with a dbt project and Snowflake or BigQuery:

```markdown
# Project config

## Stack
- dbt project: /path/to/dbt/project
- Warehouse: snowflake (connection: prod-snowflake)
- SignalPilot MCP: signalpilot server

## Before any dbt task
1. Call `list_database_connections` to confirm `prod-snowflake` is active.
2. Call `get_project` to load the dbt project context.
3. Load the `dbt-workflow` skill — it will auto-load, but confirm it's active.

## SQL rules
- Always call `validate_sql` before `query_database`.
- For full-table scans, call `estimate_query_cost` first (Snowflake bytes billed).
- Use `get_date_boundaries` before writing date-range queries to anchor to actual data dates.

## dbt model writing
- Column aliases must match YML exactly (case-sensitive).
- Use `generate_sql_skeleton` to get the initial SQL template from YML.
- After `dbt run`, run the verifier agent to confirm column alignment and grain.

## Governance
DDL and DML are blocked by the gateway. Do not attempt CREATE, DROP, ALTER, INSERT, UPDATE, or DELETE.
```

---

## Template 3 — Multi-warehouse repo

For a project with multiple database connections (e.g. Snowflake for prod, DuckDB for dev):

```markdown
# Project config

## Connections
- prod-snowflake: Snowflake production warehouse (read-only)
- dev-duckdb: DuckDB development database (read-write for dbt models)

## Connection rules
- Always call `list_database_connections` to see which connections are available.
- For exploration and profiling, prefer `dev-duckdb` (no cost).
- For production data, use `prod-snowflake` and always run `estimate_query_cost` first.
- Use `connection_health` to verify both connections are reachable before starting.

## Dialect notes
- Snowflake: use `QUALIFY` for window filtering, `LATERAL FLATTEN` for arrays.
- DuckDB: integer division truncates (`5/2 = 2`), `INTERVAL` syntax requires quotes.
- The `snowflake-sql` and `duckdb-sql` skills handle dialect-specific patterns.

## dbt builds
- dbt targets `dev-duckdb` for local builds, `prod-snowflake` for production.
- After local build, run verifier agent before promoting to prod.
- Use `schema_diff` to compare dev and prod schemas before promoting.
```

---

## Template 4 — Governance-constrained environment

For teams with strict governance requirements:

```markdown
# Project config

## Governance rules (enforced by SignalPilot gateway)
The following are blocked at the gateway level — do not attempt them:
- DDL: CREATE, DROP, ALTER, TRUNCATE
- DML: INSERT, UPDATE, DELETE, MERGE
- Dangerous functions: pg_read_file, xp_cmdshell, LOAD_FILE, and 76 others
- INTO clauses: SELECT INTO, COPY TO
- Multi-statement queries

## Required tool call sequence for any query
1. `list_database_connections` — confirm active connection
2. `validate_sql` — check syntax and governance before execution
3. `estimate_query_cost` (BigQuery/Snowflake only) — confirm cost acceptable
4. `query_database` — execute

## Audit
Every query is logged. SQL string literals are PII-redacted in audit logs.
Use `query_history` to review recent queries.

## Budget
Session budget cap: $10.00 USD. Use `check_budget` to see remaining budget.
```

---

## Key directives to always include

These directives are useful in any project:

```markdown
# Always
- Use `list_database_connections` before any database task.
- Use `validate_sql` before `query_database` for non-trivial queries.
- Use `get_date_boundaries` before date-range queries — do not hardcode dates.

# Never
- Do not attempt DDL or DML — the gateway blocks it.
- Do not add LIMIT manually — the gateway injects it automatically.
- Do not write SQL without first exploring the schema.
```
