<div align="center">

# ⚡ SignalPilot Data Agent

### 🏆 Officially ranked #1 on [Spider 2.0-DBT](https://spider2-sql.github.io/) — **51.56**

**+7.45 points above the next best agent (Databao by JetBrains, 44.11). New SOTA on the 68-task dbt benchmark as of Apr 21, 2026.**

**Governed AI agents with connector suites and access to your data stack (db, dbt and more), optimized by [AutoFyn](https://github.com/SignalPilot-Labs/AutoFyn).**

[![GitHub stars](https://img.shields.io/github/stars/SignalPilot-Labs/signalpilot?style=social)](https://github.com/SignalPilot-Labs/signalpilot/stargazers)

[🌐 Live App](https://app.signalpilot.ai/) · [🚀 Quick Start](#quick-start) · [⭐ Star the repo](https://github.com/SignalPilot-Labs/signalpilot/stargazers) · [📊 Benchmarks](benchmark/) · [⚙️ AutoFyn](https://github.com/SignalPilot-Labs/AutoFyn) · [📅 Book a demo](https://cal.com/fahimaziz/autofyn-intro)

</div>

---

## SignalPilot Cloud

**The fastest way to get started.** No Docker, no setup — sign up and connect your databases in 60 seconds.

👉 **[app.signalpilot.ai](https://app.signalpilot.ai/)** — free tier available

1. **Sign up** at [app.signalpilot.ai](https://app.signalpilot.ai/) and create your team
2. **Connect your database** — Postgres, Snowflake, BigQuery, DuckDB, and more
3. **Get your API key** from Settings → API Keys
4. **Add to Claude Code:**

```bash
claude mcp add --transport http signalpilot https://gateway.signalpilot.ai/mcp \
  --header "Authorization: Bearer YOUR_API_KEY"
```

That's it. Claude Code now has governed access to your data stack — schema discovery, read-only SQL, dbt tools, audit logging.

**Want the full plugin with dbt skills?** Also install:

```bash
claude plugin marketplace add https://github.com/SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

---

## For Data & Platform Teams

We partner with data, analytics, and platform teams who want to put AI agents to work on real warehouse workloads — safely.

- **Governed production access** — bring SignalPilot into your Snowflake / BigQuery / Postgres / dbt stack with enterprise guardrails.
- **Harness & agent optimization with AutoFyn** — we tune your agent harness, prompts, skills, and retrieval to hit production accuracy targets on *your* data, not a leaderboard.
- **Benchmark-driven evaluation** — we bring the same eval rigor that earned us the official #1 spot on Spider 2.0-DBT (51.56, +7.45 over the runner-up) into your environment: custom task suites, regression tracking, and measurable lift.
- **Enterprise support** — SSO, private deployments, SLAs, and hands-on engineering support.

**Talk to us** about your data, dbt, or agent harness optimization workload: [cal.com/fahimaziz/autofyn-intro](https://cal.com/fahimaziz/autofyn-intro) · Learn more at [signalpilot.ai](https://www.signalpilot.ai/).

---

## Quick Start

### Option A: SignalPilot Cloud (recommended)

See [SignalPilot Cloud](#signalpilot-cloud) above — sign up, connect, go.

### Option B: Self-hosted (Docker)

```bash
git clone https://github.com/SignalPilot-Labs/signalpilot.git
cd signalpilot
docker compose up -d
# Web UI at http://localhost:3200 · MCP at http://localhost:3300/mcp
```

Then add the MCP to Claude Code:

```bash
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

And install the plugin for dbt skills:

```bash
claude plugin marketplace add ./plugin
claude plugin install signalpilot-dbt@signalpilot
```

---

## What It Does

Other MCP-DB servers don't enforce LIMIT injection, DDL blocking, dangerous function blocking, or audit logging by default. SignalPilot does — that's why agents on it set the SOTA on Spider 2.0-DBT.

```
┌─────────────────────────────────────────────────────────────┐
│  Your AI Agent (Claude Code, Agent SDK, any MCP client)     │
└────────────────────────────┬────────────────────────────────┘
                             │ MCP Protocol
┌────────────────────────────▼────────────────────────────────┐
│  SignalPilot Gateway                                         │
│  ┌────────────┐ ┌──────────────┐ ┌───────────────────────┐ │
│  │ Governance │ │ Schema       │ │ dbt & Query           │ │
│  │ • LIMIT    │ │ • DDL        │ │ • Error parser        │ │
│  │ • DDL block│ │ • Explore    │ │ • Model verification  │ │
│  │ • Fn block │ │ • Join paths │ │ • Date boundaries     │ │
│  │ • Audit    │ │ • Statistics │ │ • Grain analysis      │ │
│  └────────────┘ └──────────────┘ └───────────────────────┘ │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
   ┌─────────┐        ┌──────────┐        ┌──────────┐
   │ DuckDB  │        │ Postgres │        │Snowflake │
   └─────────┘        └──────────┘        └──────────┘
```

**Governance** — Every query is parsed to AST, validated read-only, checked against a 79-function denylist across 7 database dialects, LIMIT-injected, and audit-logged with PII redaction. Your AI agent cannot drop tables, read server files, or run unbounded queries.

**Schema Discovery** — 15+ tools for exploring databases without writing SQL: table lists, column types, sample data, join path discovery, value distributions, schema linking, DDL generation.

**dbt Intelligence** — Error parsing, model schema checking, fan-out detection, cardinality auditing, date boundary analysis, SQL skeleton generation.

---

## MCP Tools (25)

| Category | Tools |
|----------|-------|
| **Query** | `query_database`, `validate_sql`, `explain_query`, `estimate_query_cost`, `debug_cte_query` |
| **Schema** | `list_tables`, `describe_table`, `explore_table`, `explore_column`, `explore_columns`, `schema_overview`, `schema_ddl`, `schema_link`, `schema_diff`, `schema_statistics` |
| **Relationships** | `get_relationships`, `find_join_path`, `compare_join_types` |
| **dbt** | `dbt_error_parser`, `generate_sql_skeleton`, `check_model_schema`, `validate_model_output`, `audit_model_sources`, `analyze_grain` |
| **Operational** | `list_database_connections`, `connection_health`, `connector_capabilities`, `get_date_boundaries`, `check_budget`, `query_history`, `list_projects`, `get_project` |

---

## Use With Any MCP Client

### Claude Code (one-liner)

```bash
# Cloud
claude mcp add --transport http signalpilot https://gateway.signalpilot.ai/mcp \
  --header "Authorization: Bearer YOUR_API_KEY"

# Self-hosted
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

### Claude Desktop / Cursor / Any MCP Client

Add to your MCP config (`.mcp.json`, `.cursor/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "signalpilot": {
      "type": "http",
      "url": "https://gateway.signalpilot.ai/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

For self-hosted, replace the URL with `http://localhost:3300/mcp` and omit headers in local mode.

---

## Plugin (Claude Code)

The [SignalPilot plugin](https://github.com/SignalPilot-Labs/signalpilot-plugin) adds battle-tested dbt skills to Claude Code — the same skills that power the Spider 2.0-DBT SOTA.

```bash
# From the marketplace (cloud or self-hosted)
claude plugin marketplace add https://github.com/SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot

# Or from a local clone
claude plugin marketplace add ./plugin
claude plugin install signalpilot-dbt@signalpilot
```

**Included skills:**
- `dbt-workflow` — full 5-step dbt lifecycle (scan, map, validate, write, verify)
- `dbt-write` — column naming, type preservation, JOIN defaults
- `dbt-debugging` — error diagnosis, orphan patches, zero-row fixes
- `dbt-date-spines` — current_date/now() hazard detection and fixing
- `duckdb-sql` / `snowflake-sql` / `bigquery-sql` / `sqlite-sql` — dialect-specific patterns
- `sql-workflow` — structured query building with CTE verification loops

---

## Connect a Database

Via the web UI at [app.signalpilot.ai](https://app.signalpilot.ai/) or `http://localhost:3200`, or via API:

```bash
curl -X POST http://localhost:3300/api/connections \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-warehouse",
    "db_type": "postgres",
    "host": "your-db-host.com",
    "port": 5432,
    "database": "analytics",
    "username": "readonly_user",
    "password": "your_password",
    "ssl": true
  }'
```

**Supported connectors:** PostgreSQL, DuckDB, SQLite, Snowflake, BigQuery, ClickHouse, MySQL, Trino, Databricks, Redshift, MSSQL.

---

## Security

SignalPilot is built for production multi-tenant deployments:

- **Read-only governance** — all queries parsed to AST, DDL/DML blocked, dangerous functions blocked (79+ across 7 dialects)
- **Tenant isolation** — API keys, connections, and audit logs are org-scoped
- **Encryption at rest** — credentials encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
- **Audit logging** — every query logged with PII redaction (string literals replaced)
- **Rate limiting** — per-IP, per-key, and per-org rate limits with auth brute-force protection
- **Non-root containers** — gateway runs as UID 10001
- **CSP hardening** — `unsafe-eval` removed, security headers on all responses

See [SECURITY.md](SECURITY.md) for our vulnerability reporting policy.

---

## Project Structure

```
SignalPilot/
├── signalpilot/
│   ├── gateway/              # FastAPI backend — MCP server, REST API, governance
│   │   └── gateway/
│   │       ├── api/          # REST API modules
│   │       ├── connectors/   # 11 database connectors + pooling + SSH tunneling
│   │       ├── governance/   # Budget, cache, PII redaction, annotations
│   │       ├── mcp/          # 25 MCP tool definitions (modular package)
│   │       ├── engine/       # SQL validation, LIMIT injection, function denylist
│   │       ├── dbt/          # Project scanning, validation, hazard detection
│   │       ├── db/           # SQLAlchemy ORM models + async engine
│   │       └── auth.py       # Clerk JWT (cloud) / local auth + org role enforcement
│   └── web/                  # Next.js 16 frontend — dashboard, connections, query
├── plugin/                   # Claude Code plugin (10 skills, 1 verifier agent)
│   ├── agents/               # Verifier agent (7-check post-build protocol)
│   └── skills/               # dbt-workflow, sql-workflow, db-specific SQL, etc.
├── benchmark/                # Spider 2.0-DBT benchmark suite (SOTA: 51.56%)
└── docker-compose.yml        # Full stack: web, gateway, postgres, sandbox
```

---

## Community

- 🐛 [Open an issue](https://github.com/SignalPilot-Labs/signalpilot/issues) — bugs, feature requests, connector requests
- 💬 [GitHub Discussions](https://github.com/SignalPilot-Labs/signalpilot/discussions) — questions, ideas, show-and-tell
- 🔒 [Security policy](SECURITY.md) — report vulnerabilities responsibly

### Contributors

[![Contributors](https://contrib.rocks/image?repo=SignalPilot-Labs/signalpilot)](https://github.com/SignalPilot-Labs/signalpilot/graphs/contributors)

---

## Star History

If SignalPilot is useful, please ⭐ — it helps a ton.

[![Star History Chart](https://api.star-history.com/svg?repos=SignalPilot-Labs/signalpilot&type=Date)](https://star-history.com/#SignalPilot-Labs/signalpilot&Date)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
