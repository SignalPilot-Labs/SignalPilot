---
sidebar_position: 2
---

# Architecture

## System diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Your AI Agent (Claude Code, Agent SDK, any MCP client)     │
└────────────────────────────┬────────────────────────────────┘
                             │ MCP Protocol (streamable-http)
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

## Component table

| Component | Description |
|-----------|-------------|
| **Gateway** | FastAPI server exposing 32 MCP tools over streamable-http. Port `3300`. |
| **Engine** | SQL governance + multi-dialect execution. Covers PostgreSQL, MySQL, SQLite, SQL Server, Snowflake, Databricks, BigQuery. |
| **Connectors** | 11 database connectors with pooling and SSH tunneling. |
| **Store** | SQLite-backed credential, connection, and audit storage with AES-GCM encryption. |
| **Auth** | Clerk JWT verification (cloud) or API key auth (local + cloud). Org-scoped with brute-force protection. |
| **Web UI** | Next.js 16 frontend on port `3200`. Connection management, query history, dashboards. |
| **Network Validation** | SSRF protection with DNS rebinding defense for cloud warehouse connections. |
| **Plugin** | Claude Code plugin: 9 skills + verifier agent. Runs outside the gateway (local to Claude Code). |
| **sp-sandbox** | gVisor sandboxed Python execution for local filesystem operations. |

## Gateway responsibilities

The gateway is the enforcement boundary. Every MCP tool call passes through:

1. **Auth** — validate API key or Clerk JWT, resolve org/tenant
2. **Rate limiter** — per-IP, per-key, per-org throttling
3. **SQL governance** — parse, block DDL/DML, deny dangerous functions, inject LIMIT
4. **Query execution** — route to the correct connector
5. **Audit** — write log entry with PII-redacted SQL

The web UI is a separate process. It calls the gateway's REST API — it does not have direct database access.

## MCP transport

SignalPilot uses **streamable-http** — the modern MCP standard. The endpoint is:

- `/mcp` (canonical)
- `/` (backward compatibility)

The protocol is stateless per request. The gateway does not maintain websocket connections or server-sent event streams between tool calls.

## Deployment modes

### Self-hosted (Docker Compose)

```
docker compose up -d
# Web UI:   http://localhost:3200
# Gateway:  http://localhost:3300
```

Single `docker-compose.yml` brings up the gateway, web UI, PostgreSQL internal DB, and sandbox. Auth is API-key based. No Clerk required.

**Architecture:**

```
Docker Compose
  ├── web (Next.js, port 3200)
  ├── gateway (FastAPI, port 3300)
  ├── postgres (internal DB for gateway)
  └── sp-sandbox (gVisor, optional)
```

### Cloud mode

```
Clerk Auth  →  Next.js Frontend  →  Gateway  →  Cloud warehouses
                                        |
                                  API Key Auth (org-scoped)
```

Multi-tenant. Clerk JWT for SSO. Org-scoped API keys. Managed history, dashboards, encrypted credential storage.

## Security architecture

See [Security](/docs/security) for the full breakdown. Summary:

- **Read-only** — DDL/DML blocked at parse time
- **Tenant isolation** — API keys are org-scoped; cross-tenant access impossible at the data layer
- **Encryption at rest** — AES-GCM for credentials and API key secrets
- **Audit logging** — every query logged, SQL literals PII-redacted
- **Non-root containers** — gateway runs as UID 10001
- **SSRF protection** — cloud warehouse hostnames validated against allow-list

## Why governance is server-side

The governance engine runs in the gateway, not in the AI agent. This means:

- Governance applies regardless of which client calls the MCP tools
- The agent cannot bypass governance by modifying its prompts
- Audit logs are authoritative — they reflect what actually ran, not what the agent claimed
