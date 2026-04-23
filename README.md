<div align="center">

# ⚡ SignalPilot Data Agent

### 🏆 Officially ranked #1 on [Spider 2.0-DBT](https://spider2-sql.github.io/) — **51.56**

**+7.45 points above the next best agent (Databao by JetBrains, 44.11). New SOTA on the 68-task dbt benchmark as of Apr 21, 2026.**

**Governed AI agents with connector suites and access to your data stack (db, dbt and more), optimized by [AutoFyn](https://github.com/SignalPilot-Labs/AutoFyn).**

[📅 Book an intro](https://cal.com/fahimaziz/autofyn-intro) · [🌐 signalpilot.ai](https://www.signalpilot.ai/) · [🚀 Try SignalPilot](#use-with-claude-code-plugin) · [⚙️ Try AutoFyn](https://github.com/SignalPilot-Labs/AutoFyn) · [📊 See benchmarks](benchmark/)

</div>

---

## For Data & Platform Teams

We partner with data, analytics, and platform teams who want to put AI agents to work on real warehouse workloads — safely.

- **Governed production access** — bring SignalPilot into your Snowflake / BigQuery / Postgres / dbt stack with enterprise guardrails (read-only, LIMIT-injected, DDL/DML-blocked, fully audit-logged).
- **Harness & agent optimization with AutoFyn** — we tune your agent harness, prompts, skills, and retrieval to hit production accuracy targets on *your* data, not a leaderboard.
- **Benchmark-driven evaluation** — we bring the same eval rigor that earned us the official #1 spot on Spider 2.0-DBT (51.56, +7.45 over the runner-up) into your environment: custom task suites, regression tracking, and measurable lift.
- **Enterprise support** — SSO, private deployments, SLAs, and hands-on engineering support.

**Talk to us** about your data, dbt, or agent harness optimization workload: [cal.com/fahimaziz/autofyn-intro](https://cal.com/fahimaziz/autofyn-intro) · Learn more at [signalpilot.ai](https://www.signalpilot.ai/).

---

## Try SignalPilot Data Agent

**Give your AI agent governed, production-ready access to your data stack** — db, dbt, and more. Schema discovery, read-only SQL, dbt project management, all through a single MCP server. No hallucinated tables. No dropped rows. No unbounded queries.

```bash
# Start SignalPilot
git clone https://github.com/SignalPilot-Labs/signalpilot.git
cd signalpilot
docker compose up -d
# Web UI available at http://localhost:3200

# Add to Claude Code
/plugin marketplace add ./plugin
/plugin install signalpilot-dbt@signalpilot
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
# Add the marketplace and install
/plugin marketplace add ./plugin
/plugin install signalpilot-dbt@signalpilot
/reload-plugins
```

Then add a `.mcp.json` to your project root to connect the MCP server:

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

See [`plugin/README.md`](plugin/README.md) for full details on included skills and agents.

---

## Use With Any MCP Client

SignalPilot exposes a standard MCP server via streamable-http transport.

### Claude Code / Claude Desktop

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "http://localhost:3300/mcp",
      "headers": {
        "X-API-Key": "sp_your_api_key_here"
      }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "signalpilot": {
      "url": "http://localhost:3300/mcp",
      "headers": {
        "X-API-Key": "sp_your_api_key_here"
      }
    }
  }
}
```

### Generic HTTP (Any MCP Client)

```json
{
  "url": "http://localhost:3300/mcp",
  "transport": "streamable-http",
  "headers": {
    "X-API-Key": "sp_your_api_key_here"
  }
}
```

Replace `sp_your_api_key_here` with your API key from **Settings → API Keys** in the web UI. In local mode without an API key configured, the `headers` field can be omitted.

---

## Connect a Database

Via the web UI at `http://localhost:3200`, or via API:

```bash
curl -X POST http://localhost:3300/api/connections \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-warehouse",
    "db_type": "duckdb",
    "database": "/path/to/warehouse.duckdb"
  }'
```

Supported: DuckDB, PostgreSQL, SQLite, Snowflake, BigQuery.

---

## MCP Tools (40 Tools)

### Data Exploration (9 tools)

| Tool | Description |
|------|-------------|
| `list_tables` | Compact one-line-per-table overview: columns, PKs, FKs, row counts |
| `describe_table` | Full column details: types, nullability, PKs, annotations, PII flags |
| `explore_table` | Deep-dive: column details + FK refs + sample values + referenced tables |
| `explore_column` | Distinct values with counts, NULL stats, optional LIKE filter |
| `explore_columns` | Multi-column stats: distinct counts, uniqueness, min/max/avg, samples |
| `schema_overview` | Database-wide summary: table count, total rows, FK density, hub tables |
| `schema_ddl` | Full schema as CREATE TABLE DDL with FK constraints |
| `schema_statistics` | High-level stats: table sizes, FK connectivity (sorted by row count) |
| `schema_diff` | Compare current schema against last cached version (DDL changes) |

### Query Intelligence (11 tools)

| Tool | Description |
|------|-------------|
| `query_database` | Execute governed, read-only SQL with auto-LIMIT, DDL blocking, audit, PII redaction |
| `validate_sql` | Syntax + semantic validation via EXPLAIN (no execution, no budget charge) |
| `explain_query` | Execution plan with row estimates and cost warnings |
| `estimate_query_cost` | Dry-run cost estimate before executing (BigQuery: exact bytes) |
| `debug_cte_query` | Break CTE query into steps, validate each independently |
| `schema_link` | Find tables relevant to a natural-language question (NL → schema) |
| `find_join_path` | FK-based join path discovery between two tables (1–6 hops) |
| `get_relationships` | Full ERD: all FK relationships as arrows or adjacency list |
| `compare_join_types` | Compare row counts across INNER/LEFT/RIGHT/FULL OUTER JOIN |
| `get_date_boundaries` | MIN/MAX dates across all DATE/TIMESTAMP columns |
| `query_history` | Recent successful queries for a connection (session memory) |

### dbt Project Intelligence (6 tools)

| Tool | Description |
|------|-------------|
| `dbt_project_map` | Full project discovery from filesystem — models, status, deps, hazards |
| `dbt_project_validate` | Run `dbt parse` safely, surface structural errors + warnings |
| `generate_sql_skeleton` | Generate a SQL template from YML column spec + ref tables |
| `dbt_error_parser` | Parse raw dbt error output into structured diagnosis + fix suggestion |
| `fix_date_spine_hazards` | Auto-fix `current_date`/`now()` in all project + package models |
| `fix_nondeterminism_hazards` | Auto-fix window functions with ambiguous ORDER BY |

### Model Verification (4 tools)

| Tool | Description |
|------|-------------|
| `check_model_schema` | Compare materialized columns vs YML-declared columns |
| `validate_model_output` | Row count validation + fan-out detection + empty model detection |
| `analyze_grain` | Cardinality analysis: per-key distinct counts, fan-out factors |
| `audit_model_sources` | Upstream audit: source row counts, fan-out/over-filter ratios, NULL scan |

### Compute & Infrastructure (7 tools)

| Tool | Description |
|------|-------------|
| `execute_code` | Run Python 3.12 in isolated gVisor sandbox (~300ms boot, 1–300s timeout) |
| `sandbox_status` | Check gVisor availability, active VM count, health |
| `list_database_connections` | List all configured database connections |
| `connection_health` | Latency percentiles (p50/p95/p99), error rates, status per connection |
| `connector_capabilities` | Connector tier classification (Tier 1/2/3) and available features |
| `check_budget` | Remaining query budget for a session |
| `cache_status` | Query cache hit rate and statistics |

### Project Management (3 tools)

| Tool | Description |
|------|-------------|
| `create_project` | Create/register a dbt project |
| `list_projects` | List all dbt projects |
| `get_project` | Get details of a specific dbt project |

---

## Project Structure

```
SignalPilot/
├── signalpilot/
│   ├── gateway/              # FastAPI backend — MCP server, REST API, governance
│   │   └── gateway/
│   │       ├── api/          # 13 API modules, 100+ REST endpoints
│   │       ├── connectors/   # 11 database connectors + pooling + SSH tunneling
│   │       ├── governance/   # Budget, cache, PII redaction, annotations
│   │       ├── dbt/          # Project scanning, validation, hazard fixing
│   │       ├── db/           # SQLAlchemy ORM models + async engine
│   │       ├── mcp_server.py # 39 MCP tool definitions
│   │       ├── store.py      # Encrypted credential storage (Fernet/PBKDF2)
│   │       └── auth.py       # Clerk JWT (cloud) / local auth
│   └── web/                  # Next.js 16 frontend — 20 pages, Tailwind CSS
│       ├── app/              # App router pages (dashboard, connections, query, etc.)
│       ├── components/       # 20 UI components (sidebar, command palette, etc.)
│       └── lib/              # API client, auth context, hooks
├── plugin/                   # Claude Code plugin (10 skills, 1 verifier agent)
│   ├── agents/               # Verifier agent (7-check post-build protocol)
│   └── skills/               # dbt-workflow, sql-workflow, db-specific SQL, etc.
├── sp-sandbox/               # gVisor sandboxed Python execution
├── benchmark/                # Spider 2.0-DBT benchmark suite (SOTA: 51.56%)
└── docker-compose.yml        # Full stack: web, gateway, postgres, sandbox
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
