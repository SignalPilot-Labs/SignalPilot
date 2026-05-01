# Workspaces API

FastAPI service that manages Workspaces runs. Round 1 contains only the app factory; routes are added in Round 2.

## Responsibilities

- Accept prompts from `signalpilot/web/app/workspaces/` (authenticated via Clerk JWT)
- Spawn sandbox containers per run; inject inference token and per-run MCP key
- Persist run state to Postgres schema `workspaces`
- Stream run events (SSE) from the sandbox to the web client
- Gate approval actions: pause sandbox, wait for user confirmation, resume

## Round 2 Routes

```
POST   /workspaces/runs              spawn a run (returns run_id)
GET    /workspaces/runs/{id}/events  SSE stream
POST   /workspaces/runs/{id}/message follow-up prompt
POST   /workspaces/runs/{id}/approve approval gate response
POST   /workspaces/runs/{id}/stop    kill the run
GET    /workspaces/dashboards        list saved dashboards
POST   /workspaces/dashboards        create dashboard from agent output
```

## Package

```
workspaces/api/
  pyproject.toml           name = "workspaces-api"
  workspaces_api/
    __init__.py            version marker
    main.py                create_app() factory
```

---

## Round 2 — Routes, DB, Spawner (added)

### Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | /healthz | Health + deployment mode |
| POST | /v1/runs | Submit a run |
| GET | /v1/runs/{id} | Fetch run state |
| GET | /v1/runs/{id}/events | SSE stream |
| POST | /v1/runs/{id}/approve | Approve a gate |
| POST | /v1/runs/{id}/reject | Reject a gate |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SP_DEPLOYMENT_MODE` | yes | `local` or `cloud` |
| `WORKSPACES_DATABASE_URL` | yes | async SQLAlchemy URL (e.g. `postgresql+asyncpg://...`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | local mode | OAuth token for Claude Code SDK |
| `ANTHROPIC_API_KEY` | cloud BYO mode | Anthropic API key |
| `SP_GATEWAY_URL` | optional | Gateway base URL (R3+ token minting) |

### Local Development

```bash
cd workspaces/api

# Install with dev deps
pip install -e ".[dev]"

# Run migrations (requires Postgres)
export WORKSPACES_DATABASE_URL=postgresql+asyncpg://signalpilot:changeme_dev_only@localhost:5601/signalpilot
alembic upgrade head

# Start the server
export SP_DEPLOYMENT_MODE=local
export CLAUDE_CODE_OAUTH_TOKEN=<your-token>
uvicorn workspaces_api.main:app --host 0.0.0.0 --port 3400 --reload

# Run tests (SQLite in-memory — no Postgres required)
pytest -q
```

### Auth

Auth is intentionally not implemented in Round 2. Clerk JWT auth is added in Round 5.
