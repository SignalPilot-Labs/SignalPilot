# signalpilot-dbt

Claude Code plugin for governed AI database access. Adds SignalPilot MCP tools, dbt skills, and verification agents to your Claude Code session.

## Install

```bash
# 1. Add the marketplace
/plugin marketplace add ./plugin

# 2. Install the plugin
/plugin install signalpilot-dbt@signalpilot

# 3. Reload
/reload-plugins
```

### Connect the MCP server

Add a `.mcp.json` to your project root:

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "http://localhost:3300/mcp"
    }
  }
}
```

Replace `localhost:3300` with your hosted instance URL if not running locally.

> **Note:** The plugin defines a `.mcp.json` with `userConfig` variables for URL/token,
> but the userConfig prompt does not currently fire on install (known Claude Code bug).
> Use the project-level `.mcp.json` above as a workaround.

## What You Get

### MCP Tools (available when server is connected)
All SignalPilot database tools appear in your session:
- `query_database` — governed read-only SQL execution
- `dbt_project_map` / `dbt_project_validate` — dbt project analysis
- `schema_overview` / `describe_table` / `explore_table` — schema discovery
- `find_join_path` / `compare_join_types` — relationship analysis
- `check_model_schema` / `validate_model_output` — model verification
- `get_date_boundaries` / `debug_cte_query` — debugging utilities
- `execute_code` — run Python in an isolated Firecracker microVM

### Skills (invoked by Claude when relevant)
| Skill | When |
|-------|------|
| `signalpilot` | Any mention of dbt, SQL, database, or data pipeline |
| `dbt-workflow` | Starting any dbt project work |
| `dbt-write` | Writing SQL models |
| `dbt-debugging` | dbt run/parse failures |
| `dbt-date-spines` | Fixing current_date in models |
| `duckdb-sql` | DuckDB-specific syntax |
| `snowflake-sql` | Snowflake-specific syntax |
| `bigquery-sql` | BigQuery-specific syntax |
| `sqlite-sql` | SQLite-specific syntax |
| `sql-workflow` | Any SQL query task |

### Agents (invoked as subagents during dbt workflow)
| Agent | Purpose |
|-------|---------|
| `verifier` | 7-check verification of all built models |

## How It Works

1. You ask Claude to build a dbt project or write SQL
2. Claude loads the `signalpilot` skill (tools overview + skill router)
3. For dbt projects, `dbt-workflow` orchestrates a 5-step workflow using SignalPilot MCP tools
4. At Step 5, the `verifier` agent checks all models for correctness
5. You get a verified, working dbt project

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- SignalPilot running (Docker or hosted)
