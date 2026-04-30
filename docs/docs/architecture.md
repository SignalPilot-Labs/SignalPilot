---
sidebar_position: 5
---

# Architecture

## Components

| Component | Description |
|-----------|-------------|
| **Gateway** | FastAPI server exposing MCP over streamable-http |
| **Engine** | SQL governance + multi-dialect execution (Postgres, MySQL, SQLite, Snowflake, Databricks, BigQuery, MSSQL) |
| **Store** | SQLite-backed credential, connection, and audit storage with AES-GCM encryption |
| **Auth** | Clerk JWT verification (cloud) or API key auth (local + cloud) |
| **Network Validation** | SSRF protection with DNS rebinding defense for cloud warehouse connections |

## Deployment modes

### Local mode

```
Docker Compose  -->  Gateway (port 8081)  -->  Your databases
```

No auth required. The gateway runs in a single container and connects directly to databases on your network.

### Cloud mode

```
Clerk Auth  -->  Next.js Frontend  -->  Gateway  -->  Cloud warehouses
                                            |
                                      API Key Auth
```

Multi-tenant with org-scoped API keys, Clerk JWT auth, rate limiting, and SSRF protection.

## MCP Transport

SignalPilot uses **streamable-http** transport (the modern MCP standard). The endpoint is mounted at:

- `/mcp` (canonical)
- `/` (backward compatibility)
