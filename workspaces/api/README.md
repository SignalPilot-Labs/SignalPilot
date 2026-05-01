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
