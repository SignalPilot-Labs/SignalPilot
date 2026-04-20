# signalpilot-dbt

Claude Code plugin for governed AI database access. Adds SignalPilot MCP tools, dbt skills, and verification agents to your normal Claude Code session.

## Install

```bash
# From GitHub
claude plugin install github:SignalPilot-Labs/signalpilot

# From local clone
claude plugin add ./plugin
```

When prompted:
- **SignalPilot URL** → `http://localhost:8080` (Docker) or your hosted instance URL
- **API token** → leave blank for local, or paste your token for hosted

## What You Get

### MCP Tools (available automatically)
All SignalPilot database tools appear in your session:
- `query_database` — governed read-only SQL execution
- `dbt_project_map` / `dbt_project_validate` — dbt project analysis
- `schema_overview` / `describe_table` / `explore_table` — schema discovery
- `find_join_path` / `compare_join_types` — relationship analysis
- `check_model_schema` / `validate_model_output` — model verification
- `get_date_boundaries` / `debug_cte_query` — debugging utilities

### Skills (auto-invoked by Claude when relevant)
| Skill | When |
|-------|------|
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
| `explorer` | Snapshots reference tables before dbt run |
| `verifier` | 7-check verification of all built models |

## How It Works

1. You ask Claude to build a dbt project or write SQL
2. Claude auto-loads the relevant skill (e.g., `dbt-workflow`)
3. The skill orchestrates a 5-step workflow using SignalPilot MCP tools
4. At Step 5, the `verifier` agent checks all models for correctness
5. You get a verified, working dbt project

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- SignalPilot running (Docker or hosted)
