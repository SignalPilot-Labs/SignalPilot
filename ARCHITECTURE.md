# SP Research — Architecture & Operations Guide

## What Is This?

SP Research is an **autonomous self-improvement agent framework** powered by the Claude Agent SDK. It runs a CEO/Worker loop that continuously improves a target codebase on a feature branch, supervised through a real-time monitor UI, with Docker-based parallel execution.

The system is designed for **autonomous code improvement research** with full supervision, instant operator control, and detailed audit trails.

---

## Repository Structure

```
/
├── self-improve/                  # Core agent framework (~3500 lines Python)
│   ├── agent/                     # Python agent package
│   │   ├── main.py                # Orchestrator: HTTP server + run lifecycle
│   │   ├── improve.py             # CEO/Worker loop logic
│   │   ├── hooks.py               # Pre/Post tool-use audit hooks
│   │   ├── permissions.py         # Tool-call permission gating
│   │   ├── signals.py             # Real-time control signal queue
│   │   ├── session_gate.py        # Time-lock MCP tool (end_session)
│   │   ├── subagents.py           # Specialized subagent definitions
│   │   ├── run_manager.py         # Parallel worker container management
│   │   ├── git_ops.py             # Git clone, branch, commit, PR creation
│   │   ├── db.py                  # SQLite schema + async queries
│   │   └── cost.py                # Token/cost tracking
│   ├── monitor/                   # FastAPI backend for the dashboard
│   │   ├── app.py                 # REST + SSE endpoints
│   │   └── crypto.py              # Fernet encryption for stored credentials
│   ├── monitor-web/               # Next.js 16 real-time dashboard
│   │   ├── app/                   # App Router pages
│   │   ├── components/            # React components (feed, controls, sidebar, stats)
│   │   └── hooks/                 # useRuns, useSSE, useParallelRuns, useMobile
│   ├── prompts/                   # Markdown prompt templates
│   │   ├── system.md              # Main agent system prompt
│   │   └── ceo-continuation.md    # CEO round-review prompt
│   ├── docker-compose.yml         # Orchestration (3 containers)
│   ├── Dockerfile.agent           # Agent container image
│   └── Dockerfile.monitor         # Monitor container image
│
├── autocode-auth/                 # Next.js authentication service
│   ├── app/                       # Pages: signin, signup, setup
│   ├── components/                # Auth UI components
│   ├── lib/                       # NextAuth config, Prisma client
│   ├── prisma/                    # PostgreSQL schema (User, Account, CliToken)
│   ├── middleware.ts              # Route protection
│   └── __tests__/                 # Vitest unit tests
│
├── CLAUDE.md                      # Skill routing instructions
├── .claude/                       # Claude Code skills directory
└── .env.example                   # Environment variables template
```

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                          Browser (User)                          │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTP
                               ▼
                    ┌──────────────────────┐
                    │   Monitor Web        │  Next.js 16 on port 3400
                    │   (Real-time UI)     │  SSE streaming, controls
                    └──────────┬───────────┘
                               │ HTTP + SSE
                               ▼
                    ┌──────────────────────┐
                    │   Monitor API        │  FastAPI on port 3401
                    │   (REST + SSE)       │  Run data, audit, settings
                    └──────────┬───────────┘
                               │ HTTP
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
        ┌────────────┐  ┌────────────┐  ┌────────────┐
        │  Agent      │  │  Worker 1  │  │  Worker N  │   Up to 10
        │  (Primary)  │  │  (Docker)  │  │  (Docker)  │   parallel
        │  Port 8500  │  │  Port 8500 │  │  Port 8500 │   containers
        └──────┬──────┘  └────────────┘  └────────────┘
               │
               ▼
        ┌────────────┐     ┌──────────────────┐
        │  SQLite DB │ ◄──►│  Cloudflare      │
        │  /data/    │     │  Tunnel (opt.)   │
        │  improve.db│     │  Remote access   │
        └────────────┘     └──────────────────┘
```

---

## How It Operates — Step by Step

### 1. Startup

When `docker-compose up` is run, three containers start:

| Container | Role | Ports |
|-----------|------|-------|
| `improve-monitor` | Dashboard UI + API | 3400 (Next.js), 3401 (FastAPI) |
| `improve-agent` | Agent orchestrator | 8500 (internal) |
| `improve-tunnel` | Cloudflare tunnel (optional) | None (outbound only) |

The **agent container** starts a FastAPI server on port 8500 and waits for a `/start` command from the monitor.

### 2. Starting a Run

The user opens the monitor UI at `http://localhost:3400`, configures credentials (GitHub token, Claude token, target repo), and clicks **Start**.

The monitor sends a `POST /start` to the agent with:
- `branch_name` — feature branch to work on
- `custom_prompt` — optional task instructions
- `duration_minutes` — session length (0 = unlimited)
- `max_budget_usd` — cost cap
- `base_branch` — branch to fork from (default: main)
- `github_repo` — target repository

### 3. Git Setup

`git_ops.py` handles repository preparation:

1. Checks if `/home/agentuser/repo` already has the target repo cloned
2. If not (or if repo changed), clones fresh from GitHub using the PAT
3. Creates a timestamped feature branch (e.g., `improve-20260406-150212`)
4. Configures git identity and safe directories

### 4. The CEO/Worker Loop

This is the core execution model in `improve.py`:

```
┌─────────────────────────────────────────────┐
│              CEO/Worker Loop                │
│                                             │
│  ┌──────────┐    ┌──────────┐              │
│  │  Worker   │───►│   CEO    │──┐           │
│  │  Phase    │    │  Phase   │  │           │
│  │           │    │          │  │           │
│  │ Execute   │    │ Review   │  │           │
│  │ the task  │    │ output,  │  │  Loop     │
│  │           │    │ assign   │  │  until    │
│  └──────────┘    │ next     │  │  done     │
│       ▲          │ task     │  │           │
│       │          └──────────┘  │           │
│       └────────────────────────┘           │
│                                             │
│  Time-lock: end_session blocked until       │
│  duration expires or operator sends unlock  │
└─────────────────────────────────────────────┘
```

**Worker Phase:**
- The Claude Agent SDK runs with the system prompt from `prompts/system.md`
- The agent acts as a "principal engineer" — reading code, planning, delegating to subagents, committing changes
- Every tool call passes through permission checks and audit hooks

**CEO Phase (when `duration_minutes > 0`):**
- After the worker completes, the agent switches to "CEO" (Product Director) role
- Receives the CEO continuation prompt from `prompts/ceo-continuation.md`
- Reviews: time elapsed, cost so far, files changed, commits made
- Decides scope: EXPANSION / SELECTIVE EXPANSION / HOLD / REDUCTION
- Assigns the next concrete task
- Loop continues until time expires or operator stops

### 5. Subagent Delegation

The primary agent delegates to specialized subagents for parallel execution:

| Subagent | Model | Purpose |
|----------|-------|---------|
| `code-writer` | Sonnet | Feature implementation, file generation |
| `test-writer` | Sonnet | Test creation and execution |
| `frontend-builder` | Sonnet | React/Next.js components and styling |
| `qa` | Sonnet | Full QA cycle (find bugs, test, fix) |
| `investigator` | Sonnet | Root-cause debugging |
| `researcher` | Sonnet | Code exploration, documentation lookup |
| `reviewer` | Opus | Post-feature code review (mandatory) |
| `plan-reviewer` | Opus | Pre-feature architecture review |
| `design-reviewer` | Opus | Post-frontend design audit |
| `security-guard` | Opus | Security audit (OWASP Top 10) |

Each subagent runs with a restricted tool set and the work happens in parallel to speed up execution.

### 6. Real-Time Operator Control

Operators can interact with running agents in real time through control signals:

| Signal | Effect |
|--------|--------|
| **Pause** | Suspends agent execution |
| **Resume** | Resumes from pause |
| **Stop** | Graceful stop — commits work, creates PR |
| **Kill** | Immediate cancellation |
| **Inject** | Sends an operator message into the agent's conversation |
| **Unlock** | Releases the time-lock early, allowing `end_session` |

Signals are delivered via an `asyncio.Queue` for instant, non-blocking delivery — no polling delay.

### 7. Permission Gating

Every tool call is checked by `permissions.py` before execution:

1. **Credential Protection** — Blocks reads/writes to `.env`, `.pem`, `.key`, secrets, `.npmrc`, `.docker/config.json`
2. **Git Push Protection** — Only allows pushes to the configured `GITHUB_REPO`; blocks protected branches (main, master, staging, prod)
3. **Path Confinement** — File operations restricted to `/workspace`, `/home/agentuser/repo`, `/tmp`
4. **Dangerous Commands** — Blocks destructive patterns (`rm -rf /`, `mkfs.`, `dd of=/dev/`)
5. **Audit Logging** — Every allow/deny decision is recorded

### 8. Audit Trail

Every action is logged to SQLite for full traceability:

- **tool_calls table** — Every pre/post tool execution with input, output, duration, and permission status
- **audit_log table** — LLM text output, thinking, usage stats, round summaries, errors
- **control_signals table** — Every operator command with timestamps

### 9. Run Completion

When a run ends (time expired, operator stop, budget exceeded, or agent calls `end_session`):

1. Final commit of any pending changes
2. PR creation via GitHub CLI (`gh pr create`)
3. Diff stats captured and stored
4. Run status updated to `completed` (or `stopped`/`error`/`killed`)
5. Cost totals finalized

---

## Parallel Execution

The `RunManager` class in `run_manager.py` supports up to **10 concurrent agent containers**:

- Each worker runs as a **sibling Docker container** (spawned via the Docker socket)
- Workers get their own isolated repo volume but share the SQLite database
- The monitor UI shows all parallel workers in a grid view
- Each worker can be independently controlled (pause/stop/inject/unlock)
- Orphan cleanup handles stray containers from previous crashes

---

## Database Schema

### Core Tables (SQLite at `/data/improve.db`)

**runs** — Run metadata
- `id`, `branch_name`, `status` (running/completed/stopped/error/killed/rate_limited)
- `total_cost_usd`, `total_tool_calls`, token counts
- `sdk_session_id` (for resumable runs), `pr_url`, `diff_stats`

**tool_calls** — Tool execution log
- `run_id`, `tool_name`, `phase` (pre/post), `input_data`, `output_data`
- `duration_ms`, `permitted`, `deny_reason`, `agent_role` (worker/ceo)

**audit_log** — Event stream
- `run_id`, `event_type` (run_started, llm_text, llm_thinking, usage, tool_call, etc.)
- `details` (JSON blob)

**control_signals** — Operator commands
- `run_id`, `signal` (pause/resume/inject/stop/unlock), `payload`, `consumed`

**workers** — Parallel container tracking
- `container_name`, `run_id`, `status`, `prompt`, `volume_name`

**settings** — Encrypted credentials
- `key`, `value`, `encrypted` flag (Fernet symmetric encryption)

---

## Authentication Service (autocode-auth)

A standalone Next.js application providing user authentication:

- **Providers:** GitHub OAuth, Google OAuth, email/password credentials
- **Session:** JWT-based via NextAuth 5.0
- **Database:** PostgreSQL via Prisma ORM
- **Password Policy:** 8-128 characters, bcrypt hashed (12 rounds)
- **CLI Tokens:** Short-lived (10-minute expiry), SHA256 hashed, max 5 per user
- **Protected Routes:** Middleware enforces authentication on `/setup`

### Prisma Models
- `User` — id, name, email, passwordHash, emailVerified
- `Account` — OAuth account linking (provider, providerAccountId, tokens)
- `CliToken` — hashedToken, expiresAt, createdAt

---

## Key Technologies

| Layer | Technology |
|-------|-----------|
| Agent Runtime | Claude Agent SDK (Python) |
| Agent API | FastAPI + Uvicorn |
| Monitor Backend | FastAPI + aiosqlite |
| Monitor Frontend | Next.js 16, React 19, Tailwind CSS 4, Framer Motion |
| Auth Service | Next.js, NextAuth 5.0, Prisma 6.0 |
| Database | SQLite (WAL mode) for agent data, PostgreSQL for auth |
| Containers | Docker, Docker Compose |
| Remote Access | Cloudflare Tunnel (cloudflared) |
| Git Integration | GitHub CLI (gh) |
| Browser Automation | Playwright MCP server |
| Encryption | Fernet (cryptography library) |

---

## Configuration

### Required Environment Variables

| Variable | Purpose |
|----------|---------|
| `GIT_TOKEN` | GitHub PAT with repo scope |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code CLI authentication |
| `GITHUB_REPO` | Target repo (e.g., `YourOrg/RepoName`) |

### Optional Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_BUDGET_USD` | 0 (unlimited) | Cost cap per run |
| `AGENT_MODEL` | opus | Primary Claude model |
| `AGENT_FALLBACK_MODEL` | sonnet | Fallback on rate limit |
| `SP_BENCHMARK_DIR` | — | Host path for benchmark data |

---

## Docker Volumes

| Volume | Purpose | Shared? |
|--------|---------|---------|
| `improve-db` | SQLite database | Yes (monitor + agent + workers) |
| `claude-agent-sessions` | Claude CLI cache/sessions | Yes (agent + workers) |
| `agent-repo` | Cloned target repo | Agent only (workers get isolated copies) |

---

## Notable Design Patterns

### Time-Locked Sessions
When `duration_minutes > 0`, the `end_session` MCP tool is blocked until the timer expires. This forces the agent to keep working within the allocated time window. The operator can send an `unlock` signal to release the lock early.

### Instant Signal Delivery
Control signals use `asyncio.Queue` for zero-latency delivery. No polling intervals — signals are consumed on the next loop iteration.

### Subagent Timeout Enforcement
A background "pulse checker" task monitors subagent activity. Subagents are killed after 45 minutes absolute or 10 minutes of idle time.

### Resumable Runs
SDK session IDs are stored in the database. Rate-limited or paused runs can be resumed from where they left off via `POST /resume/{run_id}`.

### Hook-Based Audit
Pre/post tool-use hooks capture every tool call with full input/output, enabling complete replay and forensic analysis of agent behavior.

---

## Typical Workflow

1. `docker-compose up` starts the three containers
2. Open `http://localhost:3400` in browser
3. Configure credentials in Settings (first time only)
4. Click Start with a custom prompt and duration
5. Watch real-time progress in the feed view
6. Use Pause/Inject/Unlock to steer the agent as needed
7. Agent creates commits and a PR automatically
8. Review the PR on GitHub
9. Stop the run when satisfied (or let the timer expire)

---

## Security Model

- **Non-root execution** — Agent runs as `agentuser` inside containers
- **Path confinement** — File operations restricted to designated directories
- **Branch protection** — Cannot push to main/master/staging/prod
- **Credential isolation** — Secrets encrypted at rest, never exposed to the agent
- **Permission auditing** — Every tool call decision logged with allow/deny reasoning
- **Dangerous command blocking** — Destructive shell patterns are blocked at the permission layer
