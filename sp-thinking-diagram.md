# SignalPilot: Complete System Architecture

> Every feature, every tool, every endpoint, every page — the full picture.

SignalPilot is a governed AI data platform with three pillars: an **MCP Server** (40 tools for AI agents), a **Gateway API** (100+ REST endpoints with 7-layer governance), and a **Web App** (20 pages for human operators). It connects to 11 database engines, isolates code execution in gVisor sandboxes, and orchestrates up to 4 specialized AI agents per task. The benchmark harness (Spider2-DBT SOTA: 51.56%) demonstrates the complete workflow.

---

## System Topology

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              SIGNALPILOT ECOSYSTEM                                │
│                                                                                   │
│  ┌─────────────────┐   ┌──────────────────────┐   ┌───────────────────────────┐  │
│  │   WEB APP        │   │   GATEWAY API         │   │   MCP SERVER (Plugin)     │  │
│  │   Next.js 16     │   │   FastAPI + uvicorn   │   │   40 tools for AI agents  │  │
│  │   20 pages       │   │   100+ REST endpoints │   │   10 skills on-demand     │  │
│  │   :3200          │   │   :3300               │   │   1 verifier agent        │  │
│  └────────┬─────────┘   └──────────┬────────────┘   └─────────────┬─────────────┘  │
│           │                        │                               │               │
│           └────────────────────────┼───────────────────────────────┘               │
│                                    │                                               │
│                    ┌───────────────┼───────────────┐                               │
│                    ▼               ▼               ▼                               │
│  ┌─────────────────────┐ ┌──────────────┐ ┌───────────────────┐                   │
│  │  GOVERNANCE STACK    │ │  SANDBOX     │ │  11 DATABASE      │                   │
│  │  7 layers, fail-     │ │  gVisor      │ │  CONNECTORS       │                   │
│  │  closed design       │ │  :8080       │ │  Tier 1/2/3       │                   │
│  └─────────────────────┘ └──────────────┘ └───────────────────┘                   │
│                                                                                   │
│  ┌────────────────────────────────────────────────────────────────────────────┐   │
│  │                        IMMUTABLE AUDIT TRAIL                                │   │
│  │   queries · executions · blocks · connections · cost · PII redactions       │   │
│  └────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1 — MCP Server & Plugin

The plugin lives at `signalpilot/plugin/` and exposes SignalPilot as a Claude Code plugin with 40 MCP tools, 10 loadable skills, and 1 verifier agent.

### Plugin Directory Structure

```
plugin/
├── .claude-plugin/
│   ├── marketplace.json          # Plugin marketplace metadata
│   └── plugin.json               # Plugin manifest (name, version, userConfig)
├── .mcp.json                     # MCP HTTP connection template
├── agents/
│   └── verifier.md               # Post-build 7-check verification agent
└── skills/
    ├── signalpilot/              # BLOCKING router — loads first on dbt/SQL mention
    ├── dbt-workflow/             # 5-step dbt lifecycle (entry point)
    │   └── scan_project.py       # Project scanner utility
    ├── dbt-write/                # SQL model writing rules
    ├── dbt-debugging/            # Error diagnosis & recovery
    ├── dbt-date-spines/          # current_date hazard auto-fix
    ├── sql-workflow/             # 8-step SQL query building
    ├── duckdb-sql/               # DuckDB-specific syntax & gotchas
    ├── snowflake-sql/            # Snowflake-specific patterns
    ├── bigquery-sql/             # BigQuery-specific patterns
    └── sqlite-sql/               # SQLite-specific patterns
```

### Complete MCP Tool Reference (40 Tools)

#### Data Exploration — understand what you have (9 tools)

| Tool | Purpose |
|------|---------|
| `list_tables` | Compact one-line-per-table overview: columns, PKs, FKs, row counts |
| `describe_table` | Full column details: types, nullability, PKs, annotations, PII flags |
| `explore_table` | Deep-dive: column details + FK refs + sample values + referenced tables |
| `explore_column` | Distinct values with counts, NULL stats, optional LIKE filter (ReFoRCE iterative) |
| `explore_columns` | Multi-column stats: distinct counts, uniqueness, min/max/avg, samples |
| `schema_overview` | Database-wide summary: table count, total rows, FK density, hub tables |
| `schema_ddl` | Full schema as CREATE TABLE DDL with FK constraints |
| `schema_statistics` | High-level stats: table sizes, FK connectivity (sorted by row count) |
| `schema_diff` | Compare current schema against last cached version (DDL changes) |

#### Query Intelligence — write better SQL (11 tools)

| Tool | Purpose |
|------|---------|
| `query_database` | Execute governed, read-only SQL with auto-LIMIT, DDL blocking, audit, PII redaction |
| `validate_sql` | Syntax + semantic validation via EXPLAIN (no execution, no budget charge) |
| `explain_query` | Execution plan with row estimates and cost warnings |
| `estimate_query_cost` | Dry-run cost estimate before executing (BigQuery: exact bytes) |
| `debug_cte_query` | Break CTE query into steps, validate each independently (ReFoRCE-style) |
| `schema_link` | Find tables relevant to a natural-language question (NL → schema) |
| `find_join_path` | FK-based join path discovery between two tables (1–6 hops, explicit + inferred) |
| `get_relationships` | Full ERD: all FK relationships as arrows or adjacency list |
| `compare_join_types` | Compare row counts across INNER/LEFT/RIGHT/FULL OUTER JOIN (shows unmatched rows) |
| `get_date_boundaries` | MIN/MAX dates across all DATE/TIMESTAMP columns |
| `query_history` | Recent successful queries for a connection (session memory) |

#### dbt Project Intelligence — understand the project (6 tools)

| Tool | Purpose |
|------|---------|
| `dbt_project_map` | Full project discovery from filesystem (works on broken projects) — models, status, deps, hazards. Focus options: all, work_order, missing, stubs, sources, macros, model:\<name\> |
| `dbt_project_validate` | Run `dbt parse` safely and surface structural errors + warnings + orphan patches |
| `generate_sql_skeleton` | Generate a SQL template from YML column spec + ref tables |
| `dbt_error_parser` | Parse raw dbt error output into structured diagnosis + fix suggestion |
| `fix_date_spine_hazards` | Auto-fix `current_date`/`now()` in all project + package models (creates local overrides) |
| `fix_nondeterminism_hazards` | Auto-fix window functions with ambiguous ORDER BY (append tiebreaker columns) |

#### Model Verification — prove it's correct (4 tools)

| Tool | Purpose |
|------|---------|
| `check_model_schema` | Compare materialized columns vs YML-declared columns (missing/extra/case mismatches) |
| `validate_model_output` | Row count validation + fan-out detection + empty model detection post-build |
| `analyze_grain` | Cardinality analysis: per-key distinct counts, fan-out factors, grain recommendation |
| `audit_model_sources` | Single-call upstream audit: source row counts, fan-out/over-filter ratios, NULL/constant column scan |

#### Compute & Infrastructure (7 tools)

| Tool | Purpose |
|------|---------|
| `execute_code` | Run Python 3.12 in isolated gVisor sandbox (~300ms boot, 1–300s timeout) |
| `sandbox_status` | Check gVisor availability, active VM count, health |
| `list_database_connections` | List all configured database connections |
| `connection_health` | Latency percentiles (p50/p95/p99), error rates, status per connection |
| `connector_capabilities` | Connector tier classification (Tier 1/2/3) and available features |
| `check_budget` | Remaining query budget for a session |
| `cache_status` | Query cache hit rate and statistics |

#### Project Management (3 tools)

| Tool | Purpose |
|------|---------|
| `create_project` | Create/register a dbt project |
| `list_projects` | List all dbt projects |
| `get_project` | Get details of a specific dbt project |

### Skills Architecture (10 Skills)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           SKILLS SCHEDULE                                 │
│                                                                           │
│  BLOCKING   ──▶  signalpilot         Router — loads FIRST on any          │
│                                       dbt/SQL/database mention             │
│                                                                           │
│  Step 0     ──▶  dbt-workflow         5-step lifecycle: Map → Validate    │
│                                       → Understand → Write → Verify       │
│                                                                           │
│  Step 3     ──▶  dbt-write            Column naming, JOIN defaults,       │
│                                       sibling patterns, materialization    │
│                + {db}-sql             Database-specific syntax:             │
│                                       duckdb / snowflake / bigquery /     │
│                                       sqlite (loaded per backend)          │
│                                                                           │
│  Step 4     ──▶  dbt-debugging        Error recovery: duplicate patches,  │
│                                       ref not found, zero-row, fan-out    │
│              + dbt-date-spines        current_date → data-driven MAX()    │
│                                                                           │
│  Step 5     ──▶  verifier agent       7-check post-build validation       │
│                                                                           │
│  SQL tasks  ──▶  sql-workflow         8-step SQL query building with      │
│                                       verification loop                    │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Skill Details

| Skill | When Loaded | Key Rules |
|-------|-------------|-----------|
| **signalpilot** | BLOCKING — first on any dbt/SQL mention | Routes to correct skill, lists all tools |
| **dbt-workflow** | Start of any dbt project work | 5 steps: Map → Validate → Understand contracts → Write → Verify. Never run bare `dbt run`. Don't modify .yml |
| **dbt-write** | Step 4 (writing SQL models) | YML column names are exact-match. Sibling models: read first, replicate patterns. LEFT JOIN default + COALESCE metrics. Always `materialized='table'`. No arbitrary filters |
| **dbt-debugging** | When `dbt run`/`dbt parse` fails | Duplicate YML patches, ref not found → ephemeral stubs, current_date hazards, ROW_NUMBER non-determinism, zero-row binary search, fan-out pre-aggregation |
| **dbt-date-spines** | When `dbt_project_map` warns about current_date | Replace `CURRENT_DATE` → `(SELECT MAX(date_col) FROM ref('source'))`. For package models: copy SQL locally as override |
| **sql-workflow** | Before writing any SQL query | 8 steps: schema explore → output shape inference → iterative CTE build → verify (row count, NULL audit, fan-out, sample) → save result.sql + result.csv |
| **duckdb-sql** | DuckDB backends | Integer division truncates, DATE_TRUNC→TIMESTAMP, INTERVAL syntax, QUALIFY clause, GENERATE_SERIES for date spines, avoid CURRENT_DATE |
| **snowflake-sql** | Snowflake backends | QUALIFY, LATERAL FLATTEN, ILIKE, LISTAGG, TRY_CAST, time travel |
| **bigquery-sql** | BigQuery backends | Backtick-quoted tables, UNNEST, DATE_DIFF(end,start), EXCEPT/REPLACE, wildcard tables, partition filters |
| **sqlite-sql** | SQLite backends | substr/instr, \|\| concat, date() functions, CAST only, no FULL OUTER JOIN, GROUP_CONCAT |

### Verifier Agent (7-Check Protocol)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    VERIFIER AGENT (Post-Build)                             │
│                                                                           │
│  Model: Claude Opus 4.6 (strongest reasoning)                             │
│  Invoked: Agent tool with subagent_type="signalpilot-dbt:verifier"       │
│                                                                           │
│  ┌─ Check 1: Model Existence ──────────────────────────────────────────┐ │
│  │  Read YML → glob models/**/*.sql → list_tables → compare            │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│  ┌─ Check 2: Column Schema ───────────────────────────────────────────┐  │
│  │  check_model_schema for each model (missing/extra/case mismatch)    │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│  ┌─ Check 3: Row Count ───────────────────────────────────────────────┐  │
│  │  Compare materialized count vs reference_snapshot.md                 │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│  ┌─ Check 4: Fan-Out Detection ───────────────────────────────────────┐  │
│  │  SELECT key, COUNT(*) GROUP BY 1 HAVING COUNT(*) > 1                │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│  ┌─ Check 5: Cardinality Audit ───────────────────────────────────────┐  │
│  │  audit_model_sources (fan-out/over-filter ratios, NULL scan)        │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│  ┌─ Check 6: Value Spot-Check ────────────────────────────────────────┐  │
│  │  Query sample row from reference, compare all column values          │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│  ┌─ Check 7: Table Name Verification ─────────────────────────────────┐  │
│  │  list_tables → verify all expected table names exist                  │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  DO NO HARM Rules:                                                        │
│  • Do NOT add WHERE IS NOT NULL filters                                   │
│  • Do NOT remove COALESCE from metrics                                    │
│  • Do NOT over-deduplicate with ROW_NUMBER                                │
│  • Do NOT replace NULL period-over-period columns                         │
│  • Do NOT change JOIN types without sibling evidence                      │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Part 2 — Gateway API (100+ Endpoints)

The gateway at `signalpilot/gateway/` is a FastAPI application that serves both the REST API (for the web app) and the MCP server (for AI agents). Every database interaction passes through the 7-layer governance stack.

### Middleware Stack (execution order, outermost → innermost)

```
Request →
  1. CORSMiddleware              Allows GET|POST|PUT|DELETE|OPTIONS from configured origins
  2. RequestBodySizeLimitMiddleware   Rejects bodies >2MB (HTTP 413)
  3. SecurityHeadersMiddleware   X-Content-Type-Options, X-Frame-Options, etc.
  4. RateLimitMiddleware         General: 120 rpm, expensive: 30 rpm, auth: 10 rpm
  5. RequestCorrelationMiddleware X-Request-ID header tracking
  6. APIKeyAuthMiddleware        Authorization: Bearer <key> or X-API-Key validation
  7. MCP (mounted at /)         FastMCP streamable-http endpoint
→ Handler
```

### Authentication (4 Methods)

| Method | Mode | How |
|--------|------|-----|
| **Clerk JWT** | Cloud | OAuth via CLERK_PUBLISHABLE_KEY, JWT verification |
| **Local API Key** | Dev | Auto-generated `sp_` key stored in `~/.signalpilot/` |
| **Stored API Keys** | Both | Database-persisted keys with scopes (sp_ prefixed) |
| **MCP API Keys** | Plugin | Separate MCPAuthMiddleware validation |

**Scopes:** `read` · `query` · `write` · `execute` · `admin` — flat model, no inheritance, fail-closed.

### Complete API Endpoint Reference

#### Health & Status (3 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/health` | public | Health check (no auth) |
| GET | `/metrics` | read | Live SSE stream of gateway metrics |
| GET | `/security/status` | admin | Encryption health, credential stats, key version |

#### Connections (33 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/connections` | read | List all connections |
| POST | `/api/connections` | write | Create new connection |
| GET | `/api/connections/{name}` | read | Get single connection |
| PUT | `/api/connections/{name}` | write | Update connection |
| DELETE | `/api/connections/{name}` | write | Delete connection |
| POST | `/api/connections/{name}/clone` | write | Clone existing connection |
| POST | `/api/connections/{name}/test` | read | Test connection (ping) |
| POST | `/api/connections/test-credentials` | write | Validate credentials before saving |
| POST | `/api/connections/validate-url` | read | Validate connection URL format |
| POST | `/api/connections/parse-url` | read | Parse URL into components |
| POST | `/api/connections/build-url` | read | Build URL from components |
| GET | `/api/connections/health` | read | Health stats for all connections |
| GET | `/api/connections/{name}/health` | read | Health for single connection |
| GET | `/api/connections/{name}/health/history` | read | Historical health data |
| GET | `/api/connections/stats` | read | Dashboard stats (tables, columns, rows) |
| POST | `/api/connections/{name}/schema/refresh` | write | Force schema refresh |
| POST | `/api/connections/schema/warmup` | write | Batch schema refresh for all |
| POST | `/api/connections/{name}/diagnose` | read | Full connection diagnostics |
| GET | `/api/network/info` | admin | Network configuration info |
| POST | `/api/connections/export` | write | Export all connections as JSON |
| POST | `/api/connections/import` | write | Import connections from manifest |
| GET | `/api/connectors/capabilities` | read | Capabilities & tiers for all DB types |
| GET | `/api/connections/{name}/capabilities` | read | Specific connection capabilities |

#### Schema Introspection (20 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/connections/{name}/schema` | read | Full schema (compact mode, filter, cached) |
| GET | `/api/connections/{name}/schema/grouped` | read | Table groups (ReFoRCE-style dedup) |
| GET | `/api/connections/{name}/schema/samples` | read | Sample values per column |
| POST | `/api/connections/{name}/schema/explore` | write | Iterative column exploration |
| GET | `/api/connections/{name}/schema/compact` | read | Compressed DDL-style (60-70% token reduction) |
| GET | `/api/connections/{name}/schema/enriched` | read | Schema with endorsement filters |
| GET | `/api/connections/{name}/schema/ddl` | read | CREATE TABLE statements |
| GET | `/api/connections/{name}/schema/agent-context` | read | Semantic model + schema for LLM agents |
| GET | `/api/connections/{name}/schema/link` | read | Schema linking hints (NL → tables) |
| POST | `/api/connections/{name}/schema/refine` | write | Manual schema refinement |
| GET | `/api/connections/{name}/schema/explore-table` | read | Deep dive into single table |
| GET | `/api/connections/{name}/schema/overview` | read | High-level schema overview |
| GET | `/api/connections/{name}/schema/relationships` | read | Foreign key relationships |
| GET | `/api/connections/{name}/schema/join-paths` | read | Inferred join paths |
| GET | `/api/connections/{name}/schema/search` | read | Full-text search tables/columns |
| GET | `/api/connections/{name}/schema/diff` | read | Changes since last refresh |
| GET | `/api/connections/{name}/schema/diff-history` | read | Historical schema changes |
| GET | `/api/connections/{name}/schema/refresh-status` | read | Current refresh status |
| GET | `/api/connections/{name}/schema/filter` | read | Applied include/exclude filters |
| GET | `/api/connections/{name}/schema/endorsements` | read | Endorsed tables |
| GET | `/api/schema/changes` | read | Global schema changes across all connections |

#### Query Execution (2 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST | `/api/query` | query | Execute SQL with full governance (LIMIT injection, DDL blocking, PII redaction, audit, caching, cost estimation) |
| POST | `/api/query/explain` | query | EXPLAIN query without execution |

#### Projects / dbt (6 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/projects` | read | List dbt projects |
| POST | `/api/projects` | write | Create new project |
| GET | `/api/projects/{name}` | read | Get project details |
| PUT | `/api/projects/{name}` | write | Update project |
| DELETE | `/api/projects/{name}` | write | Delete project |
| POST | `/api/projects/{name}/scan` | write | Re-scan project |

#### Sandboxes (5 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/sandboxes` | read | List all sandboxes |
| POST | `/api/sandboxes` | execute | Create new sandbox (gVisor isolated) |
| GET | `/api/sandboxes/{id}` | read | Get sandbox details |
| DELETE | `/api/sandboxes/{id}` | execute | Kill sandbox |
| POST | `/api/sandboxes/{id}/execute` | execute | Execute Python code in sandbox |

#### Budget & Annotations (6 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| POST | `/api/budget` | write | Create session budget |
| GET | `/api/budget` | read | List all session budgets |
| GET | `/api/budget/{session_id}` | read | Get budget status |
| DELETE | `/api/budget/{session_id}` | write | Close budget |
| GET | `/api/connections/{name}/annotations` | read | Load schema annotations (blocked tables, PII rules) |
| POST | `/api/connections/{name}/annotations/generate` | write | Auto-generate skeleton schema.yml |
| POST | `/api/connections/{name}/detect-pii` | write | Auto-detect PII columns by pattern |

#### Caching (5 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/cache/stats` | read | Query cache statistics |
| POST | `/api/cache/invalidate` | write | Clear query cache |
| GET | `/api/schema-cache/stats` | read | Schema cache hit/miss stats |
| POST | `/api/schema-cache/invalidate` | write | Clear schema cache |
| GET | `/api/pool/stats` | read | Connection pool statistics |

#### Audit & Compliance (2 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/audit` | admin | Query audit log (filterable by connection, event_type) |
| GET | `/api/audit/export` | admin | Export audit as JSON or CSV (SOC 2/HIPAA ready) |

#### API Keys & Settings (5 endpoints)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/keys` | admin | List API keys (redacted) |
| POST | `/api/keys` | admin | Create API key with scopes |
| DELETE | `/api/keys/{key_id}` | admin | Delete API key |
| GET | `/api/settings` | admin | Load gateway settings (redacted secrets) |
| PUT | `/api/settings` | admin | Update settings |

#### File Browser (1 endpoint)

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| GET | `/api/files/browse` | read | Browse host filesystem (for local DB file selection) |

### 7-Layer Governance Stack

```
Every query passes through ALL layers — fail-closed design.
If any layer is unavailable, ALL queries are blocked.

  ┌─────────────────────────────────────┐
  │  1. SQL AST VALIDATION (sqlglot)    │  Parse query → extract tables/columns.
  │     Fail-closed: parser missing =   │  Block: DDL, DML, DROP, TRUNCATE,
  │     ALL queries blocked.            │  multi-statement, null bytes, banned tables.
  ├─────────────────────────────────────┤
  │  2. LIMIT INJECTION                 │  No LIMIT? Inject default (10K).
  │     AST-level, not string hacking.  │  Existing LIMIT > max? Clamp down.
  │     Dialect-aware (LIMIT/TOP/FETCH).│  Respects: postgres, mysql, bigquery, etc.
  ├─────────────────────────────────────┤
  │  3. QUERY CACHE                     │  Key: (connection, normalized SQL, row_limit).
  │     Normalized: ignores whitespace. │  Hit → skip execution (0ms, logged as cache_hit).
  │     Cached AFTER PII redaction.     │  TTL-based invalidation.
  ├─────────────────────────────────────┤
  │  4. BUDGET ENFORCEMENT              │  Per-session USD limit.
  │     Cost = elapsed × $0.000014/vCPU.│  Exhausted → reject query with budget error.
  │     BigQuery: exact bytes billed.   │
  ├─────────────────────────────────────┤
  │  5. EXECUTION                       │  Read-only, timeout-enforced (1–300s).
  │     Via pooled connector.           │  Retry: exponential backoff (0.5→1→2s, max 3).
  │     Health metrics recorded.        │  SSH tunneling if configured.
  ├─────────────────────────────────────┤
  │  6. PII REDACTION                   │  40+ auto-detect patterns (email, phone,
  │     Three modes: hash, mask, drop.  │  SSN, credit card, etc.).
  │     Column-level rules from         │  Applied post-query, pre-return.
  │     schema annotations.             │  Rule-based, not LLM-based.
  ├─────────────────────────────────────┤
  │  7. AUDIT LOG                       │  Every query logged: SQL, tables touched,
  │     Immutable append-only.          │  rows returned, duration_ms, cost, cache_hit,
  │     Exportable: JSON/CSV.           │  blocked (+ reason), PII redacted, agent_id.
  └─────────────────────────────────────┘
```

### Connector Layer (11 Databases)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       CONNECTOR POOL                                      │
│                                                                           │
│  TIER 1 — Full Support                                                    │
│  ┌───────────┐  ┌───────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │ PostgreSQL │  │   MySQL   │  │  Snowflake  │  │    BigQuery     │    │
│  └───────────┘  └───────────┘  └─────────────┘  └─────────────────┘    │
│                                                                           │
│  TIER 2 — Stable                                                          │
│  ┌───────────┐  ┌───────────┐  ┌─────────────┐  ┌───────────┐          │
│  │  Redshift  │  │ClickHouse│  │ Databricks  │  │   MSSQL   │          │
│  └───────────┘  └───────────┘  └─────────────┘  └───────────┘          │
│  ┌───────────┐                                                            │
│  │   Trino   │                                                            │
│  └───────────┘                                                            │
│                                                                           │
│  TIER 3 — Basic                                                           │
│  ┌───────────┐  ┌───────────┐                                            │
│  │   DuckDB  │  │  SQLite   │                                            │
│  └───────────┘  └───────────┘                                            │
│                                                                           │
│  Shared capabilities:                                                     │
│  • Connection pooling (300s idle timeout, reuse by connection string)     │
│  • Exponential backoff retry (0.5s → 1s → 2s, max 3 attempts)           │
│  • SSH tunneling (password, key, ssh-agent, HTTP proxy)                  │
│  • SSL/TLS temp file management                                           │
│  • IAM token generation (AWS RDS)                                         │
│  • Health monitoring (p50/p95/p99 latency, error rates, windowed)        │
│  • Schema caching with mtime-based invalidation + scheduled refresh      │
│  • Identifier quoting (SQL injection prevention)                          │
│  • Read-only transaction enforcement                                      │
│  • Foreign key detection + sample value extraction                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### Gateway Internal Architecture

```
signalpilot/gateway/gateway/
├── main.py              FastAPI app, lifespan, middleware, router registration
├── auth.py              User identity resolution (Clerk JWT, local mode)
├── middleware.py         Auth, rate limiting, body size, security headers
├── correlation.py        Request ID tracking (X-Request-ID)
├── models.py            20+ Pydantic models (connections, keys, sandboxes, etc.)
├── store.py             Persistent store (SQLAlchemy, encrypted credentials)
├── scope_guard.py        Scope enforcement for API keys (fail-closed)
├── errors.py            Error codes, hints, credential sanitization
├── schema_utils.py       DDL parsing, schema introspection
├── network_validation.py SSRF prevention
├── sandbox_client.py     HTTP client to sandbox manager
├── mcp_server.py         MCP tool definitions (40 tools via @mcp.tool())
├── mcp_auth.py           MCP authentication middleware
├── cli.py               `sp` command for local key generation
│
├── api/                  13 API modules, 100+ REST endpoints
│   ├── connections.py    33 endpoints
│   ├── schema.py         20 endpoints
│   ├── query.py          2 endpoints
│   ├── projects.py       6 endpoints
│   ├── sandboxes.py      5 endpoints
│   ├── budget.py         4 + 2 annotation endpoints
│   ├── cache.py          5 endpoints
│   ├── audit.py          2 endpoints
│   ├── keys.py           3 endpoints
│   ├── settings.py       2 endpoints
│   ├── metrics.py        3 endpoints
│   ├── files.py          1 endpoint
│   ├── security.py       1 endpoint
│   └── health.py         1 endpoint
│
├── connectors/           11 database connectors + infrastructure
│   ├── base.py           Abstract BaseConnector
│   ├── postgres.py, mysql.py, sqlite.py, duckdb.py
│   ├── snowflake.py, bigquery.py, redshift.py
│   ├── clickhouse.py, databricks.py, trino.py, mssql.py
│   ├── registry.py       Connector factory
│   ├── pool_manager.py   Connection pooling + SSH tunneling
│   ├── schema_cache.py   In-memory schema cache with fingerprinting
│   ├── health_monitor.py Health tracking (p50/p95/p99)
│   └── ssh_tunnel.py     SSH tunnel management
│
├── governance/           5 governance modules
│   ├── budget.py         Session budget ledger
│   ├── cache.py          Query result caching (normalized SQL keys)
│   ├── pii.py            PII detection & redaction (40+ patterns)
│   ├── annotations.py    Schema annotations loading (blocked tables, PII rules)
│   └── cost_estimator.py Cost estimation via EXPLAIN
│
├── dbt/                  8 dbt modules
│   ├── scanner.py        Project file scanning
│   ├── validator.py      Manifest validation
│   ├── inventory.py      Model/source/test discovery
│   ├── cache.py          Manifest caching
│   ├── formatters.py     Output formatting
│   ├── work_order.py     Execution orchestration
│   ├── date_spine_fixer  current_date hazard auto-fix
│   └── nondeterminism_fixer  ROW_NUMBER ambiguity fix
│
└── db/                   Database persistence
    ├── models.py         SQLAlchemy ORM models
    └── engine.py         AsyncIO database engine setup
```

### Security Features

| Feature | Implementation |
|---------|---------------|
| **Credential encryption** | Fernet (AES-128-CBC + HMAC-SHA256), PBKDF2 key derivation (600k iterations), encrypted salt at `~/.signalpilot/.encryption_salt` |
| **Input validation** | Connection URL validation (SSRF prevention), SQL length limit (100KB), request body limit (2MB), connection string limit (4KB) |
| **SQL safety** | Block DDL/DML/DROP/TRUNCATE at AST parse level, blocked table lists via annotations, LIMIT injection (dialect-aware) |
| **Error sanitization** | Regex-based credential redaction from error messages, max error length (500 chars), contextual hints per DB type |
| **Rate limiting** | General: 120 rpm, expensive: 30 rpm, auth: 10 rpm. Per-IP or per-user configurable |
| **Audit trail** | Immutable append-only, exportable JSON/CSV, tracks: SQL, tables, rows, duration, cost, blocked reason, cache_hit |

---

## Part 3 — Web App (20 Pages)

The web app at `signalpilot/web/` is a Next.js 16 TypeScript application with Tailwind CSS, Clerk auth, and 20 pages for human operators.

### All Pages

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            WEB APP PAGES                                  │
│                                                                           │
│  CORE PAGES (9)                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ /               Landing — terminal boot animation → /dashboard      │ │
│  │ /dashboard      Main dashboard — metrics, governance viz, activity  │ │
│  │ /connections    Database connection management (CRUD + diagnostics)  │ │
│  │ /schema         Schema explorer (tables, columns, types, FKs, PII)  │ │
│  │ /query          SQL query executor (templates, results, CSV export)  │ │
│  │ /projects       dbt project management (list, create, import)       │ │
│  │ /projects/[name] Project detail (info, scan, delete)                │ │
│  │ /sandboxes      gVisor sandbox management (create, execute, kill)   │ │
│  │ /audit          Audit log with filters, search, heatmap, CSV export │ │
│  │ /health         Connection health monitoring (latency, cache stats)  │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  SETTINGS (5)                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ /settings           Gateway settings (sandbox, limits, blocked tbls)│ │
│  │ /settings/api-keys  API key management (create/delete with scopes) │ │
│  │ /settings/billing   Subscription & billing (cloud mode, Stripe)     │ │
│  │ /settings/usage     Usage analytics (7-day trends, per-key stats)   │ │
│  │ /settings/mcp-connect  MCP server config (Claude, Cursor, Generic) │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  AUTH & ONBOARDING (3)                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ /sign-in        Clerk sign-in (cloud mode only)                     │ │
│  │ /sign-up        Clerk sign-up (cloud mode only)                     │ │
│  │ /onboarding     4-step onboarding (Welcome → API Key → MCP → Done) │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  SYSTEM (2)                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ /loading         Loading skeleton                                    │ │
│  │ /not-found       404 error page                                      │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  API ROUTE (1)                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ /api/local-key   GET — returns SP_LOCAL_API_KEY from env             │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

### All Components (20 UI Components)

| Component | Purpose |
|-----------|---------|
| **sidebar.tsx** | Fixed left sidebar with 9 nav shortcuts (1-9 keys), logo with rotating status ring, uptime counter, Clerk user section |
| **clerk-user-button.tsx** | Clerk user menu (profile, sign-out) |
| **command-palette.tsx** | Cmd+K fuzzy search — navigate pages + create actions |
| **keyboard-shortcuts.tsx** | ? key opens shortcut help modal |
| **governance-pipeline.tsx** | SQL governance processing visualization (6-step pipeline) |
| **data-viz.tsx** | RingGauge, Sparkline, StatusDot, MiniBar, StackedBar, ResponsiveAreaChart, ActivityDots |
| **code-block.tsx** | Syntax-highlighted code with copy button |
| **sql-highlight.tsx** | SQL keyword/literal/identifier color-coding |
| **system-diagram.tsx** | ASCII system architecture diagram |
| **page-header.tsx** | Page title/description + TerminalBar with status |
| **page-transition.tsx** | Fade-in animation on route change |
| **section-header.tsx** | Section heading component |
| **breadcrumb.tsx** | Navigation breadcrumbs |
| **toast.tsx** | Toast notification system (success/error/warning, auto-dismiss) |
| **tooltip.tsx** | Hover tooltips with positioning |
| **confirm-dialog.tsx** | Confirmation modal for destructive actions |
| **copy-button.tsx** | Copy-to-clipboard with "copied" state |
| **skeleton.tsx** | Loading skeletons (Dashboard, ApiKeys, Billing, etc.) |
| **empty-states.tsx** | EmptyTerminal, EmptyDatabase, EmptyQuery, EmptySandbox, EmptyProject |
| **error-boundary.tsx** | React error boundary with fallback UI |
| **grid-background.tsx** | SVG animated grid pattern background |
| **time-ago.tsx** | Live relative timestamps |

### Hooks & Contexts

| Hook/Context | Purpose |
|-------------|---------|
| **useAppAuth()** | Dual-mode auth: Clerk (cloud) or local (no auth). Returns isAuthenticated, isCloudMode, user, signOut |
| **useConnection()** | Selected connection + list, persisted to localStorage, auto-refresh |
| **useSubscription()** | Plan tier, status, max API keys. Cloud: fetches from backend. Local: hardcoded "team" |
| **useOnboardingStatus()** | Onboarding completion flag (Clerk user metadata) |
| **useToast()** | Toast notifications |

### API Client (50+ Functions in `lib/api.ts`)

**Connections:** getConnections, createConnection, updateConnection, deleteConnection, testConnection, cloneConnection, diagnoseConnection, exportConnections, importConnections, validateConnectionUrl, parseConnectionUrl, browseFiles

**Schema:** getConnectionSchema, refreshConnectionSchema, searchConnectionSchema, exploreColumns, getConnectionSchemaDiff, getConnectionSchemaDDL, getConnectionSchemaLink, getSchemaEndorsements, detectPII, getSemanticModel, generateSemanticModel

**Queries:** executeQuery, explainQuery, getBudgets, createBudget, getBudget

**Projects:** getProjects, getProject, createProject, deleteProject, scanProject

**Sandboxes:** getSandboxes, createSandbox, getSandbox, deleteSandbox, executeSandbox

**Infrastructure:** getSettings, updateSettings, getHealth, getCacheStats, invalidateCache, getSchemaCache, getGatewayApiKeys, createGatewayApiKey, deleteGatewayApiKey, getAudit, getConnectionsHealth, subscribeMetrics

### Deployment Modes

| Mode | Auth | Features |
|------|------|----------|
| **Cloud** (`NEXT_PUBLIC_DEPLOYMENT_MODE=cloud`) | Clerk JWT | Sign-in/up, onboarding, billing, usage analytics, subscription tiers, rate limiting |
| **Local** (default) | None | Full access, no auth pages, mock usage data, hardcoded "team" tier |

---

## Part 4 — Sandbox (gVisor)

The sandbox at `sp-sandbox/` provides isolated Python code execution via gVisor.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      GVISOR SANDBOX ARCHITECTURE                          │
│                                                                           │
│  Agent calls execute_code("import pandas as pd; ...")                     │
│                    │                                                      │
│                    ▼                                                      │
│  ┌──────────────────────────────────────┐                                │
│  │  SANDBOX MANAGER (FastAPI :8080)     │                                │
│  │                                      │                                │
│  │  1. Validate request                 │                                │
│  │  2. Create temp directory            │                                │
│  │  3. Symlink file mounts from host    │                                │
│  │  4. Strip sensitive env vars:        │                                │
│  │     DATABASE_URL, CLERK_SECRET_KEY,  │                                │
│  │     SP_ENCRYPTION_KEY, API keys...   │                                │
│  │  5. Spawn subprocess:               │                                │
│  │     sandbox_exec.sh → setpriv →     │                                │
│  │     drop to nobody (UID 65534) →    │                                │
│  │     runsc (gVisor ptrace mode)      │                                │
│  │  6. Capture stdout (max 1MB)        │                                │
│  │  7. Return result + destroy temp    │                                │
│  └──────────────────────────────────────┘                                │
│                                                                           │
│  ISOLATION BOUNDARIES:                                                    │
│  ┌──────────────────────────────────────┐                                │
│  │ • gVisor ptrace-based (no KVM needed)│                                │
│  │ • Privilege drop to nobody (65534)   │                                │
│  │ • CPU time limit (RLIMIT_CPU)        │                                │
│  │ • File size limit: 10MB              │                                │
│  │ • Memory limit: 512MB (container)    │                                │
│  │ • PID limit: 256                     │                                │
│  │ • Read-only filesystem (except /tmp) │                                │
│  │ • tmpfs /tmp: 100MB, noexec         │                                │
│  │ • Max output: 1MB per execution      │                                │
│  │ • Max VMs: 10 concurrent             │                                │
│  │ • Timeout: 1–300s configurable       │                                │
│  │ • No network access (backend net)    │                                │
│  │ • Env vars sanitized                 │                                │
│  │ • SHA-256 code hash in audit log     │                                │
│  │   (code itself never logged)         │                                │
│  └──────────────────────────────────────┘                                │
│                                                                           │
│  Each execution gets a FRESH isolated environment.                        │
│  No filesystem, network, or state leakage between executions.             │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Part 5 — Docker Compose Stack

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     DOCKER COMPOSE STACK                                   │
│                                                                           │
│  ┌─────────────────┐   ┌──────────────────┐   ┌───────────────────┐     │
│  │   web :3200      │   │  gateway :3300    │   │  sandbox :8080    │     │
│  │   Next.js 16     │   │  FastAPI+uvicorn  │   │  gVisor manager   │     │
│  │   React 19       │   │  MCP @ /mcp       │   │  Python 3.12      │     │
│  │   Tailwind 4     │   │  100+ endpoints   │   │  Max 10 VMs       │     │
│  └────────┬─────────┘   └────────┬──────────┘   └────────┬──────────┘     │
│           │                      │                        │               │
│           └──────── frontend network ─────────────────────┘               │
│                                  │                                        │
│                      ┌───────────┼──────────┐                            │
│                      │  backend network     │  (internal — no internet)  │
│                      │                      │                            │
│                      ▼                      ▼                            │
│            ┌──────────────────┐  ┌────────────────┐                     │
│            │  postgres :5432   │  │  sandbox :8080  │                     │
│            │  (gateway store)  │  │  (isolated)     │                     │
│            └──────────────────┘  └────────────────┘                     │
│                                                                           │
│  Sandbox constraints:                                                     │
│  cap_add: [SYS_PTRACE, SYS_ADMIN]  read_only: true                     │
│  mem_limit: 512M  cpus: 2  pids_limit: 256                              │
│  tmpfs /tmp: 100M, noexec                                                │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Part 6 — Full Workflow Example (Benchmark: shopify001)

The benchmark harness at `benchmark/` demonstrates the complete end-to-end workflow across all components.

### Phase 1 — Intake & Plan

```
                     ┌─────────────────────┐
                     │   TASK DEFINITION    │
                     │  instance_id:        │
                     │    shopify001        │
                     │  instruction:        │
                     │    "Build daily shop │
                     │     metrics model"   │
                     └──────────┬──────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                  ▼
   ┌──────────────────┐ ┌──────────────┐  ┌──────────────────┐
   │  Load Task JSONL  │ │  Load Eval   │  │  Resolve Gold DB │
   │  • instance_id    │ │  Config      │  │  • path lookup   │
   │  • instruction    │ │  • tables    │  │  • existence     │
   │  • metadata       │ │  • columns   │  │    check         │
   │                   │ │  • tolerance │  │  • build date    │
   └──────────────────┘ └──────────────┘  └──────────────────┘
              │                 │                  │
              └─────────────────┼──────────────────┘
                                ▼
                 ┌──────────────────────────┐
                 │    EVAL-CRITICAL SET     │
                 │  Which exact tables +    │
                 │  columns will be graded  │
                 └──────────────────────────┘
```

### Phase 2 — Scaffold & Context

```
SPIDER2 EXAMPLE PROJECT                         WORKING DIRECTORY
┌─────────────────────────┐                     ┌──────────────────────────────┐
│ examples/{task_id}/      │  ── copytree ──▶   │ _dbt_workdir/{task_id}/       │
│  dbt_project.yml        │                     │  dbt_project.yml             │
│  profiles.yml           │                     │  profiles.yml                │
│  models/  (stubs)       │                     │  models/  (stubs + templates)│
│  macros/                │                     │  macros/                     │
│  dbt_packages/          │                     │  dbt_packages/               │
│  *.duckdb  (source data)│                     │  *.duckdb                    │
└─────────────────────────┘                     │                              │
                                                │  + .mcp.json  (tool config)  │
                                                │  + .claude/skills/ (10 skills)│
                                                │  + CLAUDE.md  (task brief)   │
                                                │  + git init                  │
                                                │  + reference_snapshot.md     │
                                                └──────────────────────────────┘
```

#### 2a. Static Analysis (pre-agent, no LLM calls)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       PROJECT SCANNER                                      │
│  (scan_project.py — runs before agent, output injected into prompt)       │
│                                                                           │
│  YML Scan              SQL Classification        Database Scan            │
│  ┌─────────────┐       ┌──────────────────┐      ┌────────────────┐      │
│  │ Model names  │       │ Complete models  │      │ Pre-built      │      │
│  │ Columns      │       │ Stub models      │      │   tables       │      │
│  │ Descriptions │       │   (<5 chars,     │      │ Row counts     │      │
│  │ Unique keys  │       │    SELECT *,     │      │ Date ranges    │      │
│  │ Dependencies │       │    TODO markers) │      │ Column types   │      │
│  │ Sources      │       │ Missing models   │      │                │      │
│  └─────────────┘       │ Orphan SQL       │      └────────────────┘      │
│                         └──────────────────┘                              │
│  Package Audit          Macro Inventory        Ephemeral Stubs            │
│  ┌─────────────┐       ┌──────────────────┐   ┌───────────────────┐      │
│  │ Installed vs │       │ Available macros │   │ Auto-create stubs │      │
│  │ referenced   │       │ from macros/     │   │ for ref() targets │      │
│  │ packages     │       │                  │   │ that exist only   │      │
│  └─────────────┘       └──────────────────┘   │ as raw DB tables  │      │
│                                                └───────────────────┘      │
│  current_date Hazards   Date Determinism                                  │
│  ┌─────────────────┐   ┌──────────────────────────┐                      │
│  │ Flag models with │   │ gold_build_dates.json     │                      │
│  │ CURRENT_DATE or  │   │ + libfaketime injection   │                      │
│  │ now() calls      │   │ (dbt run/compile/build)   │                      │
│  └─────────────────┘   └──────────────────────────┘                      │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 2b. MCP Connection Registration

```
*.duckdb file  ──▶  register_local_connection(task_id, path)
                        │
                        ▼
              SignalPilot Gateway Store
              ┌──────────────────────┐
              │  name: "shopify001"  │
              │  type: duckdb        │
              │  path: /workdir/...  │
              │  governance: ON      │
              └──────────────────────┘

From this point, every database interaction goes through the governed gateway.
```

### Phase 3 — Agent Loop

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            CLAUDE AGENT (Main)                                │
│                                                                               │
│  Model: Claude Sonnet/Opus 4.6    Thinking: extended (20k token budget)      │
│  Max turns: 200    Timeout: 900s  Permissions: bypassed                      │
│  Tools: 40 MCP tools + filesystem + shell                                    │
│  Skills: loaded on-demand from .claude/skills/                               │
│                                                                               │
│  ┌─ Step 0: MAP PROJECT ───────────────────────────────────────────────────┐ │
│  │  Load skill: dbt-workflow                                                │ │
│  │  Call: dbt_project_map → understand what needs building                  │ │
│  │  Call: dbt_project_validate → check for structural errors                │ │
│  │  Call: schema_overview / list_tables → understand the data               │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ Step 1: EXPLORE DATA ──────────────────────────────────────────────────┐ │
│  │  Call: describe_table → column types and details                         │ │
│  │  Call: explore_column → distinct values, NULLs, distributions            │ │
│  │  Call: query_database → sample queries, cardinality checks               │ │
│  │  Call: find_join_path → discover how tables connect                      │ │
│  │  Call: get_date_boundaries → find date ranges for spines                 │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ Step 2: FIX HAZARDS ──────────────────────────────────────────────────┐ │
│  │  Call: fix_date_spine_hazards → pin current_date to data max            │ │
│  │  Call: fix_nondeterminism_hazards → add tiebreakers to ORDER BY         │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ Step 3: WRITE SQL ────────────────────────────────────────────────────┐ │
│  │  Load skills: dbt-write + duckdb-sql (or snowflake/bigquery/sqlite)     │ │
│  │  Call: generate_sql_skeleton → starting template from YML               │ │
│  │  Call: compare_join_types → validate each JOIN decision                  │ │
│  │  Write: models/*.sql using Edit/Write tools                             │ │
│  │  Call: validate_sql → syntax check before building                      │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ Step 4: BUILD ────────────────────────────────────────────────────────┐ │
│  │  Run: dbt deps (if packages.yml exists)                                 │ │
│  │  Run: dbt run --select +model1 +model2 (never bare dbt run)            │ │
│  │                                                                          │ │
│  │  On failure → Load skill: dbt-debugging                                 │ │
│  │    Call: dbt_error_parser → structured error diagnosis                   │ │
│  │    Call: debug_cte_query → isolate failing CTE                          │ │
│  │    Fix SQL → rebuild → retry                                            │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ Step 5: VERIFY ──────────────────────────────────────────────────────┐  │
│  │  Dispatch: verifier agent (7-check protocol)                           │  │
│  │  Call: check_model_schema → column name match vs YML                   │  │
│  │  Call: validate_model_output → row count + fan-out detection            │  │
│  │  Call: audit_model_sources → upstream cardinality audit                 │  │
│  │  Call: analyze_grain → unique key verification                          │  │
│  │  Call: query_database → sample inspection, spot checks                  │  │
│  │                                                                          │  │
│  │  If mismatch found → back to Step 3, fix and rebuild                   │  │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### Every MCP Tool Call Traverses the Governance Stack

```
   Agent calls query_database("shopify001", "SELECT ...")
                          │
                          ▼
         ┌────────────────────────────────┐
         │     SIGNALPILOT GATEWAY        │
         │                                │
         │  1. SQL AST Validation         │
         │     └─ Parse with sqlglot      │
         │     └─ Block DDL/DML/banned    │
         │     └─ Extract table list      │
         │                                │
         │  2. LIMIT Injection            │
         │     └─ AST-level, dialect-     │
         │        aware (LIMIT/TOP/FETCH) │
         │                                │
         │  3. Cache Check                │
         │     └─ hit? → return cached    │
         │                                │
         │  4. Budget Check               │
         │     └─ exhausted? → reject     │
         │                                │
         │  5. Execute (read-only)        │
         │     └─ pooled connector        │
         │     └─ timeout enforced        │
         │     └─ retry with backoff      │
         │                                │
         │  6. PII Redaction              │
         │     └─ 40+ auto-detect rules   │
         │     └─ hash / mask / drop      │
         │                                │
         │  7. Audit Log                  │
         │     └─ SQL, tables, rows,      │
         │        duration, cost, agent_id│
         │                                │
         └────────────┬───────────────────┘
                      │
                      ▼
              Formatted result table
              returned to agent
```

### Phase 4 — Harden & Verify (Post-Agent Pipeline)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      POST-AGENT HARDENING PIPELINE                            │
│                                                                               │
│  ┌─ 4a. Safety Net Build ──────────────────────────────────────────────────┐ │
│  │  • dbt deps (if packages.yml exists)                                     │ │
│  │  • Create ephemeral stubs for any new ref() targets                      │ │
│  │  • dbt run --select +eval_critical_models                               │ │
│  │  • On failure → dispatch QUICK-FIX AGENT                                │ │
│  │    (200 turns, 1800s timeout, gets error output + cardinalities)         │ │
│  │  • Best-effort full dbt run --no-fail-fast                              │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ 4b. Value Verification ────────────────────────────────────────────────┐ │
│  │  MODEL: Claude Opus 4.6 (strongest reasoning)                            │ │
│  │  7 automated checks:                                                     │ │
│  │    ✓ Table exists                                                        │ │
│  │    ✓ Column completeness (vs YML contract)                               │ │
│  │    ✓ Categorical value audit (vs {% docs %} blocks)                      │ │
│  │    ✓ Row count validation                                                │ │
│  │    ✓ Numeric sample (flags all-zero / all-NULL columns)                  │ │
│  │    ✓ Cardinality sanity (top-N, rolling windows, UNION branches)         │ │
│  │    ✓ NULL/junk row filter (conservative — only all-NULL rows)            │ │
│  │  Re-run dbt to materialize any fixes                                     │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ 4c. Name Fix ─────────────────────────────────────────────────────────┐ │
│  │  Check: do all eval-critical table names exist in the DB?                │ │
│  │  If missing → dispatch NAME-FIX AGENT                                    │ │
│  │    • Finds similar existing tables (word overlap matching)               │ │
│  │    • Creates wrapper models or renames to match expected names            │ │
│  │    • dbt run --select <missing_tables>                                  │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ 4d. Post-Processing (deterministic, no LLM) ──────────────────────────┐ │
│  │                                                                          │ │
│  │  DEDUPLICATION                                                           │ │
│  │  • For models with unique key tests in YML:                              │ │
│  │    COUNT(*) vs COUNT(DISTINCT key) — if duplicates,                      │ │
│  │    ROW_NUMBER() OVER (PARTITION BY key) keeping rn=1                     │ │
│  │                                                                          │ │
│  │  MISSING COLUMN RECOVERY (three strategies, tried in order)              │ │
│  │  • Derivation: hour_X → EXTRACT(HOUR FROM X), _date → ::DATE           │ │
│  │  • Cross-table JOIN: find sibling table with the column, FK-join        │ │
│  │  • NULL placeholder: for _fivetran_synced / _fivetran_deleted           │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                          │                                                    │
│                          ▼                                                    │
│  ┌─ 4e. Flush & Release ──────────────────────────────────────────────────┐ │
│  │  • DuckDB CHECKPOINT (flush WAL to disk — prevents corruption)           │ │
│  │  • Delete SignalPilot connection (release lock)                           │ │
│  │  • 2s settle time                                                        │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Phase 5 — Evaluate vs Gold

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       EVALUATION ENGINE                                        │
│                                                                               │
│   Gold DB (reference)          Result DB (agent output)                       │
│   ┌──────────────┐             ┌──────────────┐                              │
│   │ shopify001/  │             │ _dbt_workdir/│                              │
│   │  shopify.db  │             │  shopify.db  │                              │
│   └──────┬───────┘             └──────┬───────┘                              │
│          │                            │                                       │
│          ▼                            ▼                                       │
│   ┌─────────────────────────────────────────────┐                            │
│   │          PER-TABLE COMPARISON                │                            │
│   │                                              │                            │
│   │  For each eval-critical table:               │                            │
│   │                                              │                            │
│   │  ┌─ CHECK 1: Table exists? ─────────────┐   │                            │
│   │  │  Missing → instant FAIL               │   │                            │
│   │  └──────────────────────────────────────┘   │                            │
│   │               │ pass                         │                            │
│   │               ▼                              │                            │
│   │  ┌─ CHECK 2: Row count match? ──────────┐   │                            │
│   │  │  gold rows ≠ pred rows → instant FAIL │   │                            │
│   │  └──────────────────────────────────────┘   │                            │
│   │               │ pass                         │                            │
│   │               ▼                              │                            │
│   │  ┌─ CHECK 3: Column-vector matching ────┐   │                            │
│   │  │  Select gold columns by index         │   │                            │
│   │  │  Transpose both tables to vectors     │   │                            │
│   │  │                                       │   │                            │
│   │  │  For each gold column vector:         │   │                            │
│   │  │    Search ALL pred columns for match  │   │                            │
│   │  │                                       │   │                            │
│   │  │  Matching rules:                      │   │                            │
│   │  │   • Sort both if ignore_order=true    │   │                            │
│   │  │   • NaN == NaN → match                │   │                            │
│   │  │   • Numeric: abs_tol ≤ 0.01           │   │                            │
│   │  │   • Datetime: normalize T00:00:00     │   │                            │
│   │  │   • String: exact match               │   │                            │
│   │  │                                       │   │                            │
│   │  │  ALL gold columns must find a match   │   │                            │
│   │  └──────────────────────────────────────┘   │                            │
│   │                                              │                            │
│   │  ALL tables must pass → binary PASS/FAIL     │                            │
│   └─────────────────────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Phase 6 — Audit Trail

```
/data/benchmark-audit/runs/{run_id}/
├── run_metadata.json          # run config, model, timing, pass/fail count
├── tasks/
│   └── {task_id}.json         # per-task result: pass/fail, elapsed, turns,
│                              #   tool calls, cost, usage (immutable)
├── traces/
│   └── {task_id}.json         # full agent transcript: thinking blocks,
│                              #   text messages, tool calls, tool results
├── queries/
│   └── {task_id}.jsonl        # every governed query: SQL, tables, rows,
│                              #   duration, cost, cache_hit, blocked
└── projects/
    └── {task_id}/             # archived working directory (SQL files,
                               #   dbt_project.yml, result DB, logs)
```

### Multi-Agent Orchestration

```
┌─────────────────────────┐
│       MAIN AGENT        │  Claude Sonnet/Opus 4.6
│  Full dbt workflow       │  200 turns, 900s timeout
│  10 skills loaded       │  Extended thinking (20k tokens)
│  40 MCP tools           │  + filesystem + shell
└──────────┬──────────────┘
           │
           │  dbt run fails?
           ▼
┌─────────────────────────┐
│    QUICK-FIX AGENT      │  Same model
│  Error diagnosis +       │  200 turns, 1800s timeout
│  targeted SQL repair     │  Gets: error output + cardinalities
└──────────┬──────────────┘
           │
           │  Build succeeds
           ▼
┌─────────────────────────┐
│  VALUE-VERIFY AGENT     │  Claude Opus 4.6 (strongest)
│  7-check audit           │  200 turns, 1800s timeout
│  "DO NO HARM" rule       │  Validates correctness, not just compilation
└──────────┬──────────────┘
           │
           │  Tables missing by name?
           ▼
┌─────────────────────────┐
│    NAME-FIX AGENT       │  Same model
│  Wrapper models or       │  200 turns, 1200s timeout
│  rename to match         │  Gets: missing names + similar existing tables
│  expected names          │
└─────────────────────────┘
```

### Benchmark Orchestration (run5.sh)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    BENCHMARK ORCHESTRATOR                                  │
│                                                                           │
│  64 Spider2-DBT tasks, 3 concurrent Docker containers                    │
│                                                                           │
│  For each task:                                                           │
│  1. Fresh Docker volume (zero stale data)                                │
│  2. FAKETIME from gold_build_dates.json (date determinism)               │
│  3. Claude Agent SDK with system prompt + skills                         │
│  4. Poll completion every 5s                                             │
│  5. Collect results immediately on container exit                         │
│  6. Vector matching evaluation (replicates Spider2 official comparator)  │
│                                                                           │
│  Result: SOTA 51.56% (official #1, +7.45 above next best)               │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Part 7 — Environment Variables

| Variable | Component | Purpose |
|----------|-----------|---------|
| `SP_ENCRYPTION_KEY` | Gateway | Fernet key or passphrase for credential encryption |
| `SP_BACKEND_URL` | Gateway | PostgreSQL connection string (cloud deployments) |
| `SP_ALLOWED_ORIGINS` | Gateway | CORS allowed origins |
| `SP_GATEWAY_URL` | Gateway | Override gateway URL for MCP callbacks |
| `SP_MCP_ALLOWED_HOSTS` | Gateway | Allowed hosts for MCP connections |
| `SP_ADMIN_USER_IDS` | Gateway | Comma-separated admin user IDs |
| `SP_DATA_DIR` | Gateway | Data directory (default: ~/.signalpilot/) |
| `SP_LOCAL_API_KEY` | Gateway+Web | Auto-generated local API key |
| `CLERK_PUBLISHABLE_KEY` | Gateway | Enables Clerk JWT authentication |
| `NEXT_PUBLIC_DEPLOYMENT_MODE` | Web | "cloud" for Clerk mode, else local |
| `NEXT_PUBLIC_GATEWAY_URL` | Web | Gateway API base URL (default: localhost:3300) |
| `NEXT_PUBLIC_MCP_URL` | Web | MCP endpoint for Claude/Cursor |
| `NEXT_PUBLIC_BACKEND_URL` | Web | Backend service URL (cloud mode) |

---

## Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Governed by default** | Every query through 7 layers: AST validation, LIMIT injection, cache, budget, execution, PII redaction, audit. No raw DB access. |
| **Fail-closed** | If the SQL parser is unavailable, all queries are blocked. Missing governance = no access. Unknown auth method = denied. |
| **Deterministic hardening** | Post-processing (dedup, missing columns, WAL flush) runs without LLM — pure logic, always consistent. |
| **Multi-agent resilience** | If the main agent fails, quick-fix, value-verify, and name-fix agents attempt recovery. |
| **Immutable audit** | Every run produces a complete, append-only record: agent transcript, every governed query, full project archive. Exportable JSON/CSV. |
| **Sandbox isolation** | Python executes in ephemeral gVisor containers — privilege drop to nobody, read-only FS, memory/PID/CPU limits, env sanitized. |
| **Skills over prompting** | Domain knowledge encoded as 10 loadable skills, not stuffed into system prompts. Loaded on-demand to preserve context window. |
| **Scanner-driven context** | The agent prompt is built from static analysis: exact column names, build order, row counts, hazard warnings, dependency graph. |
| **Dual-mode deployment** | Cloud (Clerk auth, billing, usage analytics) and local (no auth, full access) from the same codebase. |
| **11-database coverage** | Tier 1-3 connectors with shared capabilities: pooling, SSH tunneling, SSL, schema caching, health monitoring. |

---

## Statistics

| Metric | Value |
|--------|-------|
| MCP tools | 40 |
| Loadable skills | 10 |
| REST API endpoints | 100+ |
| Web app pages | 20 |
| UI components | 20 |
| Database connectors | 11 |
| Governance layers | 7 |
| Middleware layers | 7 |
| Auth methods | 4 |
| Agent types | 4 (main, quick-fix, value-verify, name-fix) |
| Verifier checks | 7 |
| PII detection patterns | 40+ |
| Benchmark tasks | 64 (Spider2-DBT) |
| Benchmark SOTA | 51.56% |
| Concurrent runners | 3 |
| Max sandbox VMs | 10 |
| Sandbox memory limit | 512MB |
| Sandbox PID limit | 256 |
