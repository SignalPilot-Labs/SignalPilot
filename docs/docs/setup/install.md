---
sidebar_position: 1
---

# Self-Host with Docker Compose

## Prerequisites

- Docker 24+ and Docker Compose v2
- Git
- Ports `3200` and `3300` free on localhost

## Install

```bash
git clone https://github.com/SignalPilot-Labs/signalpilot.git
cd signalpilot
docker compose up -d
```

The stack starts in the background. On first run Docker pulls the images (~500 MB total).

## Verify

```bash
# Web UI
curl http://localhost:3200
# Gateway health
curl http://localhost:3300/health
```

Web UI: `http://localhost:3200`
Gateway MCP endpoint: `http://localhost:3300/mcp`

## Ports

| Port | Service |
|------|---------|
| `3200` | Next.js web UI |
| `3300` | FastAPI gateway (MCP + REST API) |

## Environment file

Copy `.env.example` to `.env` and set your overrides before first boot:

```bash
cp .env.example .env
```

Key variables — see [Configuration](/docs/setup/configuration) for the full list.

## Tail logs

```bash
docker compose logs -f gateway
docker compose logs -f web
```

## Healthcheck

```bash
docker compose ps
# All services should show "healthy" or "running"
```

## Upgrade

```bash
git pull
docker compose pull
docker compose up -d
```

Running containers are replaced with zero-downtime rolling restart. The SQLite audit DB and credential store are in a named Docker volume and persist across upgrades.

## Connect Claude Code

After the stack is running:

```bash
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

See [Connect Claude Code](/docs/mcp/connect-claude-code) for verification steps.
