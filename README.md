# SP Research

Autonomous self-improvement agent powered by the Claude Agent SDK. A CEO/Worker loop continuously improves a target codebase on a branch, supervised by a real-time monitor UI.

## Quick Start

```bash
# 1. Copy .env and fill in tokens (or configure via the UI)
cp self-improve/.env.example .env
# Optional: GIT_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, GITHUB_REPO
# Credentials can also be configured at http://localhost:3400 (Settings / onboarding)

# 2. Start the stack
cd self-improve
docker compose up --build -d
```

**URLs after startup:**

| Service | URL | Description |
|---------|-----|-------------|
| Monitor UI | http://localhost:3400 | Agent run feed, controls (pause/stop/inject), cost tracking |
| Monitor API | http://localhost:3401 | SSE event stream, run history, control signals |

---

## Architecture

```
           Browser
              |
       localhost:3400
       Monitor Web
       (Next.js 16)
              |
       localhost:3401
       Monitor API
       (FastAPI)
              |
        +-----+-----+
        |           |
     Audit DB    Agent
     (SQLite)   :8500
               (Claude SDK)
```

---

## Docker Containers

### Self-Improve (`self-improve/docker-compose.yml`)

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `improve-monitor` | `python:3.12-slim` + `node:22` | 3400, 3401 | Next.js monitor dashboard (3400) + FastAPI backend (3401) |
| `improve-agent` | `python:3.12-slim` | 8500 | Claude Agent SDK runner with CEO/Worker loop, git, Docker CLI, Playwright |
| `improve-tunnel` | `cloudflare/cloudflared` | — | Cloudflare tunnel for remote access to monitor UI |

---

## Directory Structure

```
self-improve/
  agent/                    # Python agent package
    main.py                 # HTTP server (:8500) + agent run loop
    runner.py               # Agent execution engine (parallel slot runner)
    run_manager.py          # Run lifecycle management
    endpoints.py            # FastAPI endpoint definitions
    db.py                   # SQLite: runs, tool_calls, audit_log writes
    git_ops.py              # Branch creation, push, PR creation via gh CLI
    hooks.py                # PreToolUse/PostToolUse hooks: audit every tool call
    permissions.py          # Tool permission gating (block dangerous ops)
    prompt.py               # System/initial/continuation/CEO prompt builders
    session_gate.py         # MCP tool: time-lock enforcement + end_session
    signals.py              # Control signal handling (pause/resume/inject/stop)
    subagents.py            # Sub-agent orchestration
    tests/                  # pytest suite (unit + integration)
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
      parallel/             # Parallel run slots UI
      mobile/               # Mobile-responsive components
    hooks/                  # useRuns, useSSE, useParallelRuns
    lib/api.ts              # API client to :3401
  prompts/                  # Markdown prompt templates
    system.md               # Agent system prompt
    initial.md              # First-round task prompt
    ceo-continuation.md     # CEO review + next-task assignment template
    session-gate.md         # Time-lock rules
    stop.md                 # Graceful stop instructions
    agent-*.md              # Sub-agent role prompts (researcher, reviewer, QA, etc.)
    continuation-*.md       # Phase-specific continuations
  .claude/skills/           # Agent skill definitions (copied into work dir)
  .env.example              # Env var reference
  Dockerfile.agent          # Agent image (Python + Node + Docker CLI + gh + Playwright)
  Dockerfile.monitor        # Monitor image (Python + Node multi-stage)
  docker-compose.yml        # Full self-improve stack
  monitor-entrypoint.sh     # Starts FastAPI + Next.js in one container
```

### CEO/Worker Loop (timed sessions)

When a run has a duration lock (e.g. 4 hours), the agent operates in a two-role loop:

1. **Worker** executes the assigned task, then stops
2. **CEO (Product Director)** reviews what was done, sees the original prompt, assigns the next task
3. Repeat until time expires or operator sends `unlock`

Without a duration lock, it's single-shot: one round, then done.

---

## Environment Variables

Configured in `.env` at the project root (or via the monitor UI Settings page):

| Variable | Required | Description |
|----------|----------|-------------|
| `GIT_TOKEN` | No | GitHub PAT with repo scope |
| `CLAUDE_CODE_OAUTH_TOKEN` | No | Claude Code OAuth token (authenticates CLI + SDK) |
| `GITHUB_REPO` | No | Target repo slug (e.g. `your-org/SignalPilot`) |
| `MAX_BUDGET_USD` | No | Max budget per agent run in USD (default: `50`) |
| `SP_BENCHMARK_DIR` | No | Host path for benchmark data |

All credentials can be configured via the onboarding flow at `http://localhost:3400`.

---

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

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
