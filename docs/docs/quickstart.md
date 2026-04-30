---
sidebar_position: 1
slug: /
---

# Quickstart

**SignalPilot** is a governed MCP server for AI agents — Snowflake, BigQuery, Postgres, dbt with enterprise guardrails. One entrypoint, three pieces of infrastructure: plugin (skills + tools), MCP server, and an observability platform.

## Three commands to a working setup

```bash
# 1. Clone and start the stack
git clone https://github.com/SignalPilot-Labs/signalpilot.git
cd signalpilot
docker compose up -d
# Web UI:    http://localhost:3200
# Gateway:   http://localhost:3300

# 2. Connect the MCP server to Claude Code
claude mcp add --transport http signalpilot http://localhost:3300/mcp

# 3. (Optional) Install the plugin for skills + verifier agent
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

That's it. Claude Code now has governed access to your databases.

## What you get

- **32 MCP tools** — schema discovery, read-only SQL, dbt project management, cost estimation, join path finding
- **SQL governance** — DDL/DML blocked at parse time, auto-LIMIT injection, 79+ dangerous functions denied, full audit log
- **9 Claude Code skills** — battle-tested dbt and SQL skills that auto-load based on your task
- **Observability** — query history, latency dashboards, per-session budget caps, encrypted credential storage

## Next steps

**[Concepts](/docs/concepts)** — Mental model: gateway, governance, MCP, skills.

**[MCP Setup](/docs/mcp/connect-claude-code)** — Verify tools loaded; troubleshoot handshake.

**[Plugin](/docs/plugin)** — Install skills and the verifier agent.

**[Tools Reference](/docs/reference/tools-overview)** — All 32 tools, grouped by category.

## SignalPilot Cloud

Prefer not to self-host? [SignalPilot Cloud](https://app.signalpilot.ai) is free to start — sign up, get an API key, and point Claude Code at `https://gateway.signalpilot.ai/mcp`. See [Cloud setup](/docs/setup/cloud).
