<div align="center">

# ⚡ SignalPilot Data Agent

### 🏆 #1 on [Spider 2.0-DBT](https://spider2-sql.github.io/) — the public state of the art for AI data engineering

**65.6 — +5.3 ahead of the next-best system** (Databao by JetBrains, May 2026)  ·  **96.9% accuracy on ADE-bench**

**Governed AI agents for your data stack — db, dbt, and more.** Optimized and secured by [AutoFyn](https://github.com/SignalPilot-Labs/AutoFyn).

[![GitHub stars](https://img.shields.io/github/stars/SignalPilot-Labs/signalpilot?style=social)](https://github.com/SignalPilot-Labs/signalpilot/stargazers)

**[☁️ Try SignalPilot Cloud — free](https://app.signalpilot.ai/sign-in)**

[🚀 Self-host](#try-signalpilot-data-agent) · [📖 Docs](https://SignalPilot-Labs.github.io/SignalPilot/) · [⭐ Star the repo](https://github.com/SignalPilot-Labs/signalpilot/stargazers) · [📊 See benchmarks](https://www.signalpilot.ai/benchmark) · [🌐 signalpilot.ai](https://www.signalpilot.ai/) · [⚙️ Try AutoFyn](https://github.com/SignalPilot-Labs/AutoFyn) · [📅 Book a demo](https://cal.com/fahimaziz/autofyn-intro)

</div>

---

## For Agentic Data and Platform Teams

- **Governed production access** — Snowflake, BigQuery, Postgres, dbt with enterprise guardrails
- **Optimized & hardened by [AutoFyn](https://github.com/SignalPilot-Labs/AutoFyn)** — the autonomous security agent that's surfaced vulnerabilities in Next.js, MetaMask, and other major platforms — now tuning prompts, skills, and security guardrails for your data agents
- **Benchmark-driven evaluation** — same eval rigor that earned [#1 on Spider 2.0-DBT](https://www.signalpilot.ai/benchmark)
- **Enterprise support** — SSO, private deployments, SLAs

[Talk to us](https://cal.com/fahimaziz/autofyn-intro) · [signalpilot.ai](https://www.signalpilot.ai/)

---

## What SignalPilot Is

**One entrypoint, three pieces of infrastructure** on the same gateway.

Today the supported entrypoint is **[Claude Code](https://claude.com/claude-code)**. Underneath it, three components do the work:

1. **Plugin (skill + tool)** — [`plugin/`](plugin/) adds 10 dbt/SQL skills + a verifier agent + 32 MCP tools to your Claude Code session. This is the recommended way to use SignalPilot.
2. **MCP server** — standard `streamable-http`, the layer the plugin talks to. *Experimental for non-Claude clients*: Cursor / Codex / custom Agent SDK builds can connect and call the 32 MCP tools, but the **skills are Claude Code-specific** and don't run there. Use at your own risk until other platforms ship a skill-equivalent surface.
3. **Observability platform** — `docker compose up -d` brings up the gateway, web UI (`:3200`), audit log, query history, latency/error dashboards, encrypted credential storage. Or use [SignalPilot Cloud](https://app.signalpilot.ai/sign-in) for SSO and hosted history.

---

## Benchmarks

Most data agents look impressive in a demo and fall apart on a real warehouse. We measure ours against the field — and lead it.

### 🥇 #1 on Spider 2.0-DBT

The hardest public benchmark for AI data engineering — 68 tasks that demand real project navigation, complex SQL environments, and long-context reasoning. SignalPilot tops the leaderboard at **65.6 — +5.3 ahead of the next-best system** (Databao by JetBrains, May 2026), and well clear of the GPT-5-based agents below it. [See the leaderboard →](https://www.signalpilot.ai/benchmark)

### 🎯 96.9% on ADE-bench

Across **64 real analytics-engineering tasks** — building dbt models against live warehouses — SignalPilot's agents delivered **correct, production-ready output 62 of 64 times**. Not plausible-looking SQL: models you can ship.

> That gap is the difference between an agent you babysit and one you trust in production.

---

**Index** — [What It Is](#what-signalpilot-is) · [Benchmarks](#benchmarks) · [How It Works](#how-it-works) · [Try](#try-signalpilot-data-agent) · [Architecture](#architecture) · [MCP Tools](#mcp-tools) · [Community](#community)

---

## How It Works

Five stages, every task: plan → scan → govern → build → report.

### 01 — Describe what you need

![Describe what you need](docs/docs/images/ask.gif)

- Plain-English goal in chat (e.g. *"Build `shopify__daily_shop` — orders, abandoned checkouts, fulfillment counts by day"*)
- Parsed into a structured task — no SQL written, no warehouse touched yet

### 02 — Agent scans your project

![Agent scans your project](docs/docs/images/scanning.gif)

- Inspects dbt project + warehouse: sources, staging, marts, missing models
- Flags date hazards (`current_date`, `now()`)
- Resolves build order across the DAG — deterministic, not a guess

### 03 — Every query is governed

![Every query is governed](docs/docs/images/governance.gif)

- DDL (`DROP`, `CREATE`, `ALTER`) and DML (`INSERT`, `UPDATE`, `DELETE`) blocked at the parser
- Auto-`LIMIT` injection on unbounded `SELECT`
- Per-session budget cap kills queries that would scan over your $ threshold
- Every query audited: timestamp, agent ID, policy reason, full SQL

### 04 — Plan, build, and verify

![Plan, build, and verify](docs/docs/images/dag.gif)

- Writes a structured build spec first — sources, joins, grain, filters, expected rows per model — before a line of SQL
- `dbt parse` catches structural errors; models build in dependency order
- Read-only verification checks every built model — structure (row count, fan-out, cardinality, column completeness) **and** values — and prescribes exact fixes
- Re-verifies after each fix and stops only when every check passes

### 05 — Full audit receipt

![Full audit receipt](docs/docs/images/receipt.gif)

- Structured summary: duration · agent turns · governed queries · queries blocked · models built · columns validated
- Every line traces back to a specific MCP tool call

---

## Try SignalPilot Data Agent

**Give your AI agent governed, production-ready access to your data stack** — db, dbt, and more. Schema discovery, read-only SQL, dbt project management, all through a single MCP server. No hallucinated tables. No dropped rows. No unbounded queries.

```bash
# Start SignalPilot
git clone https://github.com/SignalPilot-Labs/signalpilot.git
cd signalpilot
docker compose up -d
# Web UI available at http://localhost:3200

# Connect the MCP server to Claude Code
claude mcp add --transport http signalpilot http://localhost:3300/mcp

# (Optional) Install the plugin for skills + agents
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

That's it. Claude Code now has governed access to your databases.

---

## Architecture

Other MCP-DB servers don't enforce LIMIT injection, DDL blocking, dangerous function blocking, or audit logging by default. SignalPilot does — that's why agents on it set the SOTA on Spider 2.0-DBT.

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

---

## Plugin (Claude Code)

The [SignalPilot plugin](https://github.com/SignalPilot-Labs/signalpilot-plugin) adds battle-tested dbt skills to Claude Code — the same skills that power the Spider 2.0-DBT SOTA.

```bash
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

**Included skills:** `dbt-workflow` (full 5-step lifecycle), `dbt-write`, `dbt-debugging`, `dbt-date-spines`, `duckdb-sql`, `snowflake-sql`, `bigquery-sql`, `sqlite-sql`, `sql-workflow`

See [`plugin/README.md`](plugin/README.md) for details.

---

## Use With Any MCP Client

> ⚠️ **Experimental for non-Claude clients.** The 32 MCP tools work over `streamable-http` from any MCP client (Cursor, Codex, custom Agent SDK) — but the SignalPilot skills are Claude Code-specific and don't run outside it. You'll have the tools without skill orchestration. The Claude Code Plugin is the supported path; treat the configs below as best-effort.

### Claude Code (one-liner)

```bash
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

### Claude Desktop / Cursor / Any MCP Client

Add to your MCP config (`.mcp.json`, `.cursor/mcp.json`, etc.):

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

When API keys are configured, add an `Authorization: Bearer YOUR_API_KEY` header.

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

## MCP Tools

35 governed tools across query execution, schema discovery, dbt intelligence, model verification, and Notion integration.

| Category | Tools |
|----------|-------|
| **Query** | `query_database`, `validate_sql`, `explain_query`, `estimate_query_cost`, `debug_cte_query` |
| **Schema** | `list_tables`, `describe_table`, `explore_table`, `explore_column`, `explore_columns`, `schema_overview`, `schema_ddl`, `schema_link`, `schema_diff`, `schema_statistics` |
| **Relationships** | `get_relationships`, `find_join_path`, `compare_join_types` |
| **dbt** | `dbt_error_parser`, `generate_sql_skeleton`, `check_model_schema`, `validate_model_output`, `audit_model_sources`, `analyze_grain` |
| **Notion** | `notion_search`, `notion_fetch_page`, `notion_create_page` |
| **Operational** | `list_database_connections`, `connection_health`, `connector_capabilities`, `get_date_boundaries`, `check_budget`, `query_history`, `list_projects`, `get_project` |

See the [full tools reference](https://SignalPilot-Labs.github.io/SignalPilot/docs/reference/tools-overview) in the docs.

---

## Security

- **Read-only governance** — queries parsed to AST, DDL/DML blocked, 79+ dangerous functions blocked across 7 dialects
- **Tenant isolation** — API keys, connections, and audit logs are org-scoped
- **Encryption at rest** — Fernet (AES-128-CBC + HMAC-SHA256)
- **Audit logging** — every query logged with PII redaction
- **Rate limiting** — per-IP, per-key, and per-org with brute-force protection
- **Non-root containers** — gateway runs as UID 10001

See [Security docs](https://SignalPilot-Labs.github.io/SignalPilot/docs/security) for our full security model and vulnerability reporting policy.

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
│   │       ├── mcp/          # 32 MCP tool definitions (modular package)
│   │       ├── engine/       # SQL validation, LIMIT injection, function denylist
│   │       ├── dbt/          # Project scanning, validation, hazard detection
│   │       ├── db/           # SQLAlchemy ORM models + async engine
│   │       └── auth.py       # Clerk JWT (cloud) / local auth + org role enforcement
│   └── web/                  # Next.js 16 frontend — 20 pages, Tailwind CSS
│       ├── app/              # App router pages (dashboard, connections, query, etc.)
│       ├── components/       # 20 UI components (sidebar, command palette, etc.)
│       └── lib/              # API client, auth context, hooks
├── plugin/                   # Claude Code plugin (10 skills, 1 verifier agent)
│   ├── agents/               # Verifier agent (7-check post-build protocol)
│   └── skills/               # dbt-workflow, sql-workflow, db-specific SQL, etc.
├── sp-sandbox/               # gVisor sandboxed Python execution
├── benchmark/                # Spider 2.0-DBT (SOTA 65.6) + ADE-bench (96.9%) suites
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
[![GitHub stars](https://img.shields.io/github/stars/SignalPilot-Labs/signalpilot?style=social)](https://github.com/SignalPilot-Labs/signalpilot/stargazers)

<a href="https://www.star-history.com/?type=date&repos=SignalPilot-Labs%2Fsignalpilot">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=SignalPilot-Labs/signalpilot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=SignalPilot-Labs/signalpilot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=SignalPilot-Labs/signalpilot&type=date&legend=top-left" />
 </picture>
</a>
---

## Contributing

Contributions are welcome — bug fixes, new connectors, docs, and features. Start with the **[Contributing Guide](CONTRIBUTING.md)** for setup, coding standards, and the PR process. For anything non-trivial, [open an issue](https://github.com/SignalPilot-Labs/signalpilot/issues) first so we can align on the approach.

- 🛠️ [Contributing Guide](CONTRIBUTING.md) — dev setup, standards, PR workflow
- 🐛 [Report a bug](https://github.com/SignalPilot-Labs/signalpilot/issues) · 💬 [Discussions](https://github.com/SignalPilot-Labs/signalpilot/discussions) · 🔒 [Security policy](SECURITY.md)

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
