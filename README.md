# SignalPilot

Governed AI database access platform with autonomous self-improvement. SQL queries go through a security gateway with PII redaction, cost budgeting, audit logging, and sandboxed execution via Firecracker microVMs. An agentic loop powered by the Claude Agent SDK continuously improves the codebase on a branch, supervised by a real-time monitor UI.

## Quick Start

```bash
# 1. Copy .env and fill in tokens
cp self-improve/.env.example .env
# Required: GIT_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, GITHUB_REPO

# 2. Start the main platform (gateway + web UI + postgres)
cd signalpilot/docker
docker compose -f docker-compose.dev.yml up --build -d

# 3. Start the self-improve stack (monitor UI + audit DB + agent)
cd ../../self-improve
docker compose up --build -d

# 4. (Optional) Start the security testing databases
cd ../testing
docker compose up -d
```

**URLs after startup:**

| Service | URL | Description |
|---------|-----|-------------|
| Web UI | http://localhost:3200 | Query editor, connections, schema browser, audit logs |
| Gateway API | http://localhost:3300 | REST + SSE API, health at `/health` |
| Monitor UI | http://localhost:3400 | Agent run feed, controls (pause/stop/inject), cost tracking |
| Monitor API | http://localhost:3401 | SSE event stream, run history, control signals |
| Sandbox Manager | http://localhost:8180 | Firecracker VM orchestrator |

---

## Architecture

```
                 Browser
                   |
        +----------+----------+
        |                     |
   localhost:3200        localhost:3400
   SignalPilot Web       Monitor Web
   (Next.js 16)         (Next.js 16)
        |                     |
   localhost:3300        localhost:3401
   Gateway API           Monitor API
   (FastAPI)             (FastAPI)
        |                     |
   +----+----+          +-----+-----+
   |         |          |           |
 Postgres  Sandbox    Audit DB    Agent
 :5600     :8180      :5610      :8500
           (Firecracker)       (Claude SDK)
```

---

## Docker Containers

### Main Platform (`signalpilot/docker/docker-compose.dev.yml`)

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `docker-gateway-1` | `python:3.12-slim` | 3300 | FastAPI gateway: query governance, connectors, audit, budget, PII redaction |
| `docker-web-1` | `node:22-alpine` | 3200 | Next.js frontend: dashboard, query editor, connections, schema browser |
| `docker-postgres-1` | `postgres:17` | 5600 | General-purpose database for connections and testing |

### Self-Improve (`self-improve/docker-compose.yml`)

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `improve-monitor` | `python:3.12-slim` + `node:22` | 3400, 3401 | Next.js monitor dashboard (3400) + FastAPI backend (3401) |
| `improve-pg` | `postgres:17` | 5610 | Audit database: runs, tool_calls, audit_log, control_signals |
| `improve-agent` | `python:3.12-slim` | 8500 | Claude Agent SDK runner with CEO/Worker loop, git, Docker CLI, Playwright |

### Sandbox (`sp-firecracker-vm/docker-compose.yml`)

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `sandbox` | `Dockerfile.gvisor` | 8080 | gVisor sandbox (default, no KVM needed, ~230ms) |
| `sandbox-firecracker` | `Dockerfile` | 8080 | Firecracker microVMs (Linux/KVM only, ~200ms) |

### Testing (`testing/docker-compose.yml`)

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `sp-enterprise-pg` | `postgres:17` | 5601 | OLTP test database (`enterprise_prod`) |
| `sp-warehouse-pg` | `postgres:17` | 5602 | Analytics test database (`analytics_warehouse`) |

---

## Directory Structure

### `signalpilot/` -- Main Platform

```
signalpilot/
  gateway/                  # Python package (pip install -e .)
    gateway/
      main.py               # FastAPI app: all REST endpoints
      engine.py             # SQL validation + LIMIT injection via sqlglot
      models.py             # Pydantic request/response models
      store.py              # File-backed state (connections, sandboxes, audit)
      middleware.py          # API key auth, rate limiting, security headers
      sandbox_client.py     # HTTP client to Firecracker manager
      mcp_server.py         # MCP protocol server for AI tool use
      cli.py                # `sp` CLI entrypoint
      connectors/
        base.py             # Abstract connector interface
        postgres.py         # asyncpg PostgreSQL driver
        sqlite.py           # aiosqlite driver
        duckdb.py           # DuckDB driver
        registry.py         # Connector type registry
        pool_manager.py     # Connection pool lifecycle
        health_monitor.py   # Per-connection health stats
        schema_cache.py     # Schema introspection cache
      governance/
        annotations.py      # schema.yml: blocked tables, PII rules, descriptions
        budget.py           # Per-session cost budgeting
        cache.py            # Query result cache (normalized SQL keys)
        cost_estimator.py   # EXPLAIN-based cost estimation
        pii.py              # PII column detection + redaction (email, SSN, phone, etc.)
    tests/                  # pytest suite
    pyproject.toml          # Package metadata + dependencies
  web/                      # Next.js 16 frontend
    app/
      page.tsx              # Home dashboard
      connections/          # Add/test/delete DB connections
      query/                # SQL editor with governed execution
      schema/               # Schema browser with PII/annotation badges
      sandboxes/            # Firecracker sandbox management
      audit/                # Audit log viewer with export
      dashboard/            # Analytics: query volume, latency, cost charts
      health/               # System health status
      settings/             # Gateway configuration
    components/
      layout/sidebar.tsx    # Navigation sidebar
      ui/governance-pipeline.tsx  # Visual governance step pipeline
    lib/
      api.ts                # Typed API client
      types.ts              # Shared TypeScript interfaces
    next.config.ts          # Rewrites /gateway/* to the API
  docker/
    Dockerfile.gateway      # Gateway image
    Dockerfile.web          # Web image (multi-stage build)
    docker-compose.yml      # Full stack (includes sandbox)
    docker-compose.dev.yml  # Dev stack (sandbox running separately)
```

### `self-improve/` -- Autonomous Agent

```
self-improve/
  agent/                    # Python agent package
    main.py                 # HTTP server (:8500) + agent run loop
    db.py                   # asyncpg: runs, tool_calls, audit_log writes
    git_ops.py              # Branch creation, push, PR creation via gh CLI
    hooks.py                # PreToolUse/PostToolUse hooks: audit every tool call
    permissions.py          # Tool permission gating (block dangerous ops)
    prompt.py               # System/initial/continuation/CEO prompt builders
    session_gate.py         # MCP tool: time-lock enforcement + end_session
  monitor/                  # FastAPI backend
    app.py                  # REST + SSE: runs, tool_calls, control signals
    models.py               # Pydantic models
  monitor-web/              # Next.js 16 dashboard
    app/page.tsx            # Main monitor view
    components/
      controls/             # Start/stop/pause/resume/inject buttons
      feed/                 # Real-time SSE event feed + LLM output viewer
      sidebar/              # Run list with status badges
      stats/                # Cost, tokens, tool call counters
    hooks/                  # useRuns, useSSE, useControl
    lib/api.ts              # API client to :3401
  prompts/                  # Markdown prompt templates
    system.md               # Agent system prompt
    initial.md              # First-round task prompt
    ceo-continuation.md     # CEO review + next-task assignment template
    session-gate.md         # Time-lock rules
    stop.md                 # Graceful stop instructions
    continuation-*.md       # Phase-specific continuations
  sql/
    init.sql                # Audit DB schema (runs, tool_calls, audit_log, control_signals)
  .claude/skills/           # Agent skill definitions (copied into work dir)
    benchmark-improvement/  # Spider2 benchmarking
    code-quality/           # Code review + error handling
    connector-development/  # New database connector creation
    frontend-debug/         # Frontend debugging with Playwright
    gateway-hardening/      # Auth, rate limiting, SQL engine
    performance/            # Optimization + profiling
    security-audit/         # Vulnerability assessment
    test-coverage/          # Testing strategy
  .env.example              # Required env vars
  Dockerfile.agent          # Agent image (Python + Node + Docker CLI + gh + Playwright)
  Dockerfile.monitor        # Monitor image (Python + Node multi-stage)
  docker-compose.yml        # Full self-improve stack
  monitor-entrypoint.sh     # Starts FastAPI + Next.js in one container
```

#### CEO/Worker Loop (timed sessions)

When a run has a duration lock (e.g. 4 hours), the agent operates in a two-role loop:

1. **Worker** executes the assigned task, then stops
2. **CEO (Product Director)** reviews what was done, sees the original prompt, assigns the next task
3. Repeat until time expires or operator sends `unlock`

Without a duration lock, it's single-shot: one round, then done.

### `sp-firecracker-vm/` -- Sandbox Manager

Auto-detecting sandbox with two backends behind one API:
- **Linux (KVM available):** Firecracker microVMs — separate guest kernel per sandbox, snapshot-accelerated (~200ms)
- **macOS / no KVM:** gVisor (Google's user-space kernel) — syscall interception via Sentry (~230ms)

Detection is automatic: if `/dev/kvm` exists → Firecracker, otherwise → gVisor. The gateway and LLM see the same `POST /execute` API regardless of backend.

```
sp-firecracker-vm/
  sandbox_manager.py        # HTTP API: /health, /execute, /vms — delegates to executor
  executor_base.py          # Abstract executor interface
  executor_firecracker.py   # Firecracker backend (Linux/KVM)
  executor_gvisor.py        # gVisor backend (macOS/anywhere)
  Dockerfile                # Firecracker image (requires --device /dev/kvm)
  Dockerfile.gvisor         # gVisor image (works everywhere, no KVM needed)
  Dockerfile.sandbox        # Self-contained Firecracker (downloads kernel + builds rootfs)
  Dockerfile.rootfs         # Python + data science rootfs builder
  rootfs/
    sandbox_agent.py        # In-VM agent: receives + executes code (vsock mode)
    sandbox_init.py         # VM boot init process (serial mode)
  scripts/
    build-rootfs.sh         # Build ext4 root filesystem image
    setup-linux.sh          # Linux host prerequisites
    setup-macos.sh          # macOS setup + backend auto-detection
    setup-network.sh        # Bridge networking for VMs
  test/boot-vm.py           # VM boot test
  signalpilot-sandbox.yml   # Sandbox configuration (local/cloud/container modes)
  docker-compose.yml        # Profiles: default (gVisor), firecracker (KVM)
  windows-instructions.md   # WSL2/KVM setup guide
```

### `benchmark/` -- Spider2 Benchmarking

```
benchmark/
  run.py                    # Main benchmark runner
  eval.py                   # Result evaluation (execution accuracy, fuzzy match)
  improve.py                # Improvement loop: benchmark → analyze → improve → re-bench
  agent_runner.py           # Claude Agent SDK execution wrapper
  skills.py                 # Skill system for specialized improvement
  setup_spider2.py          # Download + prepare Spider2 dataset
  config.py                 # Paths, model, parameters
  datasets/                 # Spider2 dataset cache
  results/                  # Benchmark run results
  skills/                   # Skill definitions
```

### `testing/` -- Security Test Databases

```
testing/
  docker-compose.yml        # Two postgres instances (OLTP + analytics)
  init_enterprise.sql       # OLTP schema + seed data
  init_warehouse.sql        # Analytics warehouse schema
  generate_data.py          # Synthetic data generator
  SECURITY_AUDIT.md         # Known vulnerabilities + remediations
```

---

## Environment Variables

Configured in `.env` at the project root:

| Variable | Required | Description |
|----------|----------|-------------|
| `GIT_TOKEN` | Yes | GitHub PAT with repo scope |
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes | Claude Code OAuth token (authenticates CLI + SDK) |
| `GITHUB_REPO` | Yes | Target repo slug (e.g. `SignalPilot-Labs/SignalPilot`) |
| `SP_BENCHMARK_DIR` | No | Host path for benchmark data (default: `D:\signalpilot-bench`) |
| `MAX_BUDGET_USD` | No | Default max budget per agent run, 0 = unlimited (default: `0`) |

Internal variables set by docker-compose (do not override):
- `AUDIT_DB_URL` -- Postgres connection string for audit DB
- `SP_SANDBOX_MANAGER_URL` -- Gateway's path to the sandbox manager
- `AGENT_API_URL` -- Monitor's path to the agent container

---

## Gateway API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System health + sandbox status |
| GET/PUT | `/api/settings` | Gateway configuration |
| GET/POST | `/api/connections` | List / create DB connections |
| GET/DELETE | `/api/connections/{name}` | Connection details / remove |
| POST | `/api/connections/{name}/test` | Test connectivity |
| GET | `/api/connections/{name}/schema` | Introspect schema (cached) |
| GET | `/api/connections/{name}/annotations` | PII rules, blocked tables |
| POST | `/api/connections/{name}/detect-pii` | Auto-detect PII columns |
| POST | `/api/query` | Execute governed SQL query |
| GET | `/api/sandboxes` | List active sandboxes |
| POST | `/api/sandboxes` | Create Firecracker sandbox |
| POST | `/api/sandboxes/{id}/execute` | Run code in sandbox |
| GET | `/api/audit` | Query audit log |
| GET | `/api/audit/export` | Export audit trail (JSON/CSV) |
| POST/GET/DELETE | `/api/budget[/{session_id}]` | Cost budget management |
| GET | `/api/cache/stats` | Query cache statistics |
| GET | `/api/metrics` | SSE live metrics stream |

## Monitor API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/runs` | List all runs |
| GET | `/api/runs/{id}` | Run details (cost, tokens, status) |
| GET | `/api/runs/{id}/tools` | Tool call history |
| GET | `/api/runs/{id}/audit` | Audit event log |
| POST | `/api/runs/{id}/pause` | Pause agent |
| POST | `/api/runs/{id}/resume` | Resume agent |
| POST | `/api/runs/{id}/inject` | Inject prompt into running agent |
| POST | `/api/runs/{id}/stop` | Graceful stop (agent commits + creates PR) |
| POST | `/api/runs/{id}/unlock` | End time-lock after current round |
| POST | `/api/agent/start` | Start new improvement run |
| POST | `/api/agent/stop` | Instant stop via in-process queue |
| POST | `/api/agent/kill` | Immediate cancel, no cleanup |
| GET | `/api/agent/health` | Agent container status |
| GET | `/api/stream/{id}` | SSE real-time event stream |
