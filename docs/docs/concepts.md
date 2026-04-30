---
sidebar_position: 2
---

# Concepts

## The mental model

SignalPilot sits between your AI agent and your databases. Every query passes through the gateway — it never runs directly against the database.

```
Claude Code  →  MCP tools  →  SignalPilot Gateway  →  Your databases
                                      |
                               Governance layer
                               (parse, block, limit, audit)
```

### Gateway

The FastAPI backend that exposes the 32 MCP tools over `streamable-http`. It handles auth, rate limiting, SQL governance, query execution, and audit logging. All governance logic lives here — the AI agent never touches the database directly.

### MCP server

SignalPilot implements the [Model Context Protocol](https://spec.modelcontextprotocol.io/) over `streamable-http`. The endpoint is `http://localhost:3300/mcp` (self-hosted) or `https://gateway.signalpilot.ai/mcp` (cloud). Any MCP client that supports `streamable-http` can connect, though the plugin skills are Claude Code-specific.

### Plugin

The [SignalPilot Claude Code plugin](https://github.com/SignalPilot-Labs/signalpilot-plugin) adds 9 battle-tested skills and a verifier agent on top of the 32 MCP tools. Skills are markdown files that load into Claude Code's context automatically based on relevance — they guide Claude's behavior without you writing prompt instructions.

### Skill

A markdown knowledge file registered with Claude Code. When a relevant task is detected, the skill auto-loads and tells Claude which tools to call, in what order, and what to watch out for. For example, `dbt-workflow` teaches Claude the 5-step plan-scan-govern-build-verify lifecycle. Skills are Claude Code-specific — they don't run in Cursor or other clients.

### Verifier agent

A post-build quality check that runs 7 verifications after `dbt run` completes: column alignment, row counts, fan-out detection, NULL scan, source row counts, schema comparison, and grain analysis. It returns a structured receipt, not just a pass/fail.

### Governance

The enforcement layer that runs on every SQL query: DDL/DML blocking, dangerous function denial, `LIMIT` injection, `INTO` clause detection, multi-statement rejection, and budget cap enforcement. Governance is fail-closed — if a rule check cannot run, the query is rejected.

### Connection

A named, encrypted database credential stored in the gateway. Each connection has a type (e.g. `snowflake`), a name used by tools like `list_database_connections`, and credentials encrypted with AES-GCM at rest.

### Project

A registered dbt project on disk. Tools like `get_project` and `list_projects` enumerate projects. The plugin's `scan_project.py` and `validate_project.py` scripts read the project locally (no MCP needed).

### Audit log

An append-only record of every tool call and query: timestamp, org, connection, SQL (with string literals PII-redacted), cost estimate, and policy decisions. Stored in the gateway's SQLite database by default; configurable for external destinations.

---

## Glossary

| Term | Definition |
|------|-----------|
| **gateway** | The FastAPI MCP server that governs all database access |
| **MCP server** | The `streamable-http` endpoint that Claude Code talks to (`/mcp`) |
| **plugin** | The Claude Code plugin that adds skills + verifier agent |
| **skill** | A markdown knowledge file that auto-loads into Claude Code's context |
| **verifier agent** | Post-build 7-check quality protocol that runs after `dbt run` |
| **governance** | The parse-time enforcement layer: DDL block, LIMIT inject, function deny |
| **connection** | An encrypted, named database credential in the gateway |
| **project** | A registered dbt project scanned by the gateway |
| **audit log** | Append-only record of every query, policy decision, and tool call |
