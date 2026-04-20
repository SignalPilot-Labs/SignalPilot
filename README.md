# SignalPilot

Governed AI database access. Connect any database, get schema discovery + read-only SQL execution + dbt project management — all through a single MCP server that any AI agent can use.

```bash
# Start SignalPilot
git clone https://github.com/SignalPilot-Labs/signalpilot.git
cd signalpilot
docker compose up -d

# Add to Claude Code
claude plugin install github:SignalPilot-Labs/signalpilot
# → SignalPilot URL: http://localhost:8080
# → API token: (leave blank for local)
```

That's it. Claude Code now has governed access to your databases.

---

## What It Does

```
┌─────────────────────────────────────────────────────────────┐
│  Your AI Agent (Claude Code, Agent SDK, any MCP client)     │
└────────────────────────────┬────────────────────────────────┘
                             │ MCP Protocol
┌────────────────────────────▼────────────────────────────────┐
│  SignalPilot Gateway                                         │
│  ┌────────────┐ ┌──────────────┐ ┌───────────────────────┐ │
│  │ Governance │ │ Schema       │ │ dbt Project           │ │
│  │ • LIMIT    │ │ • DDL        │ │ • Map / Validate      │ │
│  │ • DDL block│ │ • Explore    │ │ • Model verification  │ │
│  │ • Audit    │ │ • Join paths │ │ • Date boundaries     │ │
│  └────────────┘ └──────────────┘ └───────────────────────┘ │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
   ┌─────────┐        ┌──────────┐        ┌──────────┐
   │ DuckDB  │        │ Postgres │        │Snowflake │
   └─────────┘        └──────────┘        └──────────┘
```

**Governance** — Every query is read-only, LIMIT-injected, DDL/DML-blocked, and audit-logged. Your AI agent cannot drop tables, modify data, or run unbounded queries.

**Schema Discovery** — 10+ tools for exploring databases without writing SQL: table lists, column types, sample data, join path discovery, value distributions.

**dbt Intelligence** — Project mapping, parse validation, model schema checking, fan-out detection, cardinality auditing, date boundary analysis.

---

## Use With Claude Code (Plugin)

The [`plugin/`](plugin/) directory is a Claude Code plugin that adds all SignalPilot tools + battle-tested dbt skills to your normal Claude Code session.

```bash
# Install from local clone
claude plugin add ./plugin

# Or from GitHub
claude plugin install github:SignalPilot-Labs/signalpilot
```

See [`plugin/README.md`](plugin/README.md) for full details on included skills and agents.

---

## Use With Any MCP Client

SignalPilot exposes a standard MCP server. Add it to any client that supports MCP:

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "streamable-http",
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

Or via stdio (for SDK-based agents):

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "gateway.mcp_server"],
      "cwd": "./signalpilot/gateway",
      "env": { "PYTHONPATH": "./signalpilot/gateway" }
    }
  }
}
```

---

## Connect a Database

Via the web UI at `http://localhost:8080`, or via API:

```bash
curl -X POST http://localhost:8080/api/connections \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-warehouse",
    "db_type": "duckdb",
    "database": "/path/to/warehouse.duckdb"
  }'
```

Supported: DuckDB, PostgreSQL, SQLite, Snowflake, BigQuery.

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `query_database` | Governed read-only SQL execution |
| `list_tables` | All tables with row counts |
| `schema_overview` | Full schema summary |
| `schema_ddl` | CREATE TABLE statements |
| `describe_table` | Column names, types, constraints |
| `explore_table` | Sample rows + value distributions |
| `explore_column` | Distinct values for a column |
| `find_join_path` | Discover join paths between tables |
| `compare_join_types` | Row count comparison for each JOIN type |
| `validate_sql` | Syntax-check without executing |
| `debug_cte_query` | Run each CTE step independently |
| `explain_query` | Execution plan |
| `schema_link` | Find tables relevant to a question |
| `dbt_project_map` | Project overview: models, contracts, build order |
| `dbt_project_validate` | Run dbt parse, surface errors |
| `check_model_schema` | Compare materialized vs YML columns |
| `validate_model_output` | Row count + fan-out checks |
| `audit_model_sources` | Cardinality audit of upstream sources |
| `get_date_boundaries` | Date ranges across all tables |
| `analyze_grain` | Detect table grain from data |
| `get_relationships` | Foreign key and inferred relationships |

---

## Project Structure

| Directory | Description |
|-----------|-------------|
| `signalpilot/` | Core gateway + web UI — the MCP server |
| `plugin/` | Claude Code plugin (skills, agents, MCP config) |
| `sp-firecracker-vm/` | Firecracker/gVisor sandboxed code execution |
| `benchmark/` | Spider 2.0 benchmark suite — see [`benchmark/`](benchmark/) |

---

## Benchmarks

SignalPilot is benchmarked on [Spider 2.0](https://spider2-sql.github.io/) (dbt, Snowflake, SQLite/BigQuery). See [`benchmark/`](benchmark/) for the full harness, results, and reproduction instructions.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
