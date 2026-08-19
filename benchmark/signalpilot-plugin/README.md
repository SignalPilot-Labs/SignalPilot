# SignalPilot Plugin for Claude Code

Governed AI database access — sandboxed queries, schema discovery, and intelligent model building powered by [SignalPilot](https://signalpilot.ai).

## Install

### Step 1: Connect the MCP server

```bash
# Cloud
claude mcp add --transport http signalpilot https://gateway.signalpilot.ai/mcp \
  --header "Authorization: Bearer sp_YOUR_API_KEY"

# Local / self-hosted
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

### Step 2: Install the plugin (optional — adds skills + agents)

```bash
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

Step 1 gives you all 30+ MCP tools. Step 2 adds skills and agents on top.

## What's Included

### MCP Tools (from Step 1)

| Category | Tools |
|----------|-------|
| Schema Discovery | `schema_overview`, `list_tables`, `describe_table`, `explore_table`, `explore_column`, `explore_columns`, `get_relationships`, `schema_ddl`, `schema_link` |
| Querying | `query_database`, `validate_sql`, `explain_query`, `estimate_query_cost` |
| Analysis | `analyze_grain`, `schema_statistics`, `find_join_path`, `compare_join_types`, `get_date_boundaries`, `schema_diff` |
| Governance | `check_budget`, `query_history`, `audit_model_sources`, `validate_model_output` |
| Infrastructure | `list_database_connections`, `connection_health`, `connector_capabilities` |

### Skills (from Step 2)

| Skill | Description |
|-------|-------------|
| `/signalpilot-dbt:signalpilot` | MCP tool catalog |
| `/signalpilot-dbt:sql-workflow` | Structured SQL query building with verification |
| `/signalpilot-dbt:dbt-workflow` | Full dbt project workflow (scan, map, validate, write, verify) |
| `/signalpilot-dbt:dbt-write` | dbt model writing with column naming and type rules |
| `/signalpilot-dbt:dbt-debugging` | Fix dbt run/parse failures |
| DB-specific | `bigquery-sql`, `snowflake-sql`, `duckdb-sql`, `sqlite-sql` |

### Agents (from Step 2)

| Agent | Description |
|-------|-------------|
| `verifier` | Read-only structure verification (five checks) |
| `value-verifier` | Read-only value verification (three checks) |

## How It Works

1. Load `dbt-workflow` for a dbt project.
2. Follow its ordered workflow with SignalPilot MCP tools.
3. Use the read-only verifiers after materialization.
4. Return the verified project.

## Requirements

- [Claude Code](https://claude.ai/claude-code) CLI
- A SignalPilot account ([signalpilot.ai](https://signalpilot.ai)) or self-hosted instance

## License

Apache-2.0
