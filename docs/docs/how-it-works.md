---
sidebar_position: 4
---

# How It Works

Five stages, every task: **plan → scan → govern → build → report**.

## 01 — Describe what you need

![Describe what you need](./images/ask.gif)

- Plain-English goal in chat (e.g. *"Build `shopify__daily_shop` — orders, abandoned checkouts, fulfillment counts by day"*)
- Parsed into a structured task — no SQL written, no warehouse touched yet
- The `dbt-workflow` skill loads and guides the rest of the lifecycle

## 02 — Agent scans your project

![Agent scans your project](./images/scanning.gif)

- Inspects dbt project + warehouse: sources, staging, marts, missing models
- Flags date hazards (`current_date`, `now()`)
- Resolves build order across the DAG — deterministic, not a guess
- Tools: `list_tables`, `describe_table`, `schema_overview`, `get_project`

## 03 — Every query is governed

![Every query is governed](./images/governance.gif)

- DDL (`DROP`, `CREATE`, `ALTER`) and DML (`INSERT`, `UPDATE`, `DELETE`) blocked at the parser
- Auto-`LIMIT` injection on unbounded `SELECT`
- Per-session budget cap kills queries that would scan over your $ threshold
- Every query audited: timestamp, agent ID, policy reason, full SQL
- Tool: `query_database`, `validate_sql`, `estimate_query_cost`

## 04 — DAG builds itself

![DAG builds itself](./images/dag.gif)

- `dbt parse` runs first to catch structural errors
- Models materialized in topological order
- Verifier agent reads dbt errors and proposes fixes (renames, missing CTEs, fan-out, date-spine guards)
- Tests run after build and feed back into the loop
- Tools: `dbt_error_parser`, `generate_sql_skeleton`, `check_model_schema`

## 05 — Full audit receipt

![Full audit receipt](./images/receipt.gif)

- Structured summary: duration · agent turns · governed queries · queries blocked · models built · columns validated
- Every line traces back to a specific MCP tool call
- Tools: `audit_model_sources`, `validate_model_output`, `analyze_grain`

---

## Query lifecycle (detailed)

Every `query_database` call follows this path:

```
Agent  →  MCP request  →  Gateway  →  SQL Governance  →  Database
                              |
                        Auth + Rate Limit
                              |
                        Audit Log (PII-redacted)
```

1. Agent sends a tool call via MCP (e.g. `query_database`)
2. Auth layer validates the API key or Clerk JWT, resolves the org/tenant
3. Rate limiter checks per-key and per-org limits
4. SQL governance parses the query: blocks DDL/DML, strips dangerous functions, injects LIMIT
5. Engine executes against the target database
6. Audit logs the query with SQL literals PII-redacted
7. Response returned to the agent

## Governance rules

- **DDL/DML blocked**: No `CREATE`, `DROP`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`
- **Dangerous functions blocked**: 79+ functions across 7 SQL dialects (e.g. `pg_read_file`, `LOAD_FILE`, `xp_cmdshell`)
- **LIMIT injection**: Every SELECT gets a configurable max row limit (default: 1000)
- **INTO clause blocked**: Prevents `SELECT INTO` / `COPY TO` exfiltration
- **Stacking prevented**: Multi-statement queries are rejected

See [Governance reference](/docs/reference/governance) for the full rule set.
