---
sidebar_position: 3
---

# Security

SignalPilot was designed to make AI database access safe by default. This page covers the full security model.

## Reporting a vulnerability

If you believe you've found a security vulnerability in SignalPilot, please report it privately — do **not** open a public GitHub issue.

**Email: security@signalpilot.ai**

Please include:

- A description of the issue and its potential impact
- Steps to reproduce (proof-of-concept code or commands if available)
- The affected version, commit SHA, or deployment configuration
- Whether the issue is already public or coordinated with another party

**What to expect:**

- Acknowledgement within 3 business days
- Triage and initial assessment within 7 business days
- Coordinated disclosure — we'll work with you on a fix timeline and credit you in the advisory if you'd like

We use [GitHub Security Advisories](https://github.com/SignalPilot-Labs/signalpilot/security/advisories) to publish fixed vulnerabilities once a patch is available.

## Scope

**In scope:**

- The SignalPilot gateway (FastAPI backend, MCP server, REST API)
- The web UI (Next.js frontend)
- The Claude Code plugin
- The gVisor sandbox (`sp-sandbox/`)
- Database connectors and credential storage

**Out of scope:**

- Vulnerabilities in third-party dependencies (please report upstream)
- Issues that require a malicious admin user with full write access
- Denial-of-service via misconfiguration

## Governance

- **Read-only enforcement**: DDL and DML statements are blocked at the parse layer. No `CREATE`, `DROP`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`.
- **Dangerous function denylist**: 79+ functions blocked across PostgreSQL, MySQL, SQLite, SQL Server, Snowflake, Databricks, and BigQuery.
- **LIMIT injection**: Fail-closed — if LIMIT can't be injected, the query is rejected.
- **Multi-statement blocking**: Prevents SQL stacking attacks.
- **INTO clause detection**: Blocks `SELECT INTO`, `COPY TO`, and similar exfiltration patterns.

See [Governance reference](/docs/reference/governance) for the complete rule set.

## Authentication

- **Clerk JWT** verification with JWKS rotation, clock leeway, and required claims (cloud mode)
- **API keys** with AES-GCM encryption at rest, org-scoped, with brute-force rate limiting (60/min/IP)
- **Org role enforcement**: Admin-only endpoints require `org:admin` role

## Network

- **SSRF protection**: Cloud warehouse connection parameters validated against allowed domains (Snowflake, Databricks, BigQuery)
- **DNS rebinding defense**: Hostnames resolved and validated before connection
- **Non-root containers**: Gateway and backend run as UID 10001

## Audit

- **Every query logged** with timestamp, org, user, connection, and SQL
- **PII redaction**: SQL string literals replaced with `'***'` in audit logs
- **Query cost estimation** before execution

## Encryption

- **AES-GCM** for credential storage (connection passwords, API key secrets)
- **Legacy SHA-256** gated behind `SP_ALLOW_LEGACY_CRYPTO` flag (disabled by default)

## Rate limiting

- 60 requests/min/IP on auth endpoints (brute-force protection)
- 120 MCP tool calls/min/API key
- 300 MCP tool calls/min/org (cloud)

## Tenant isolation

In multi-tenant (cloud) mode, every API key is scoped to an org. A key can only access connections registered by that org. Cross-tenant access is blocked at the data layer — not just at the API layer.

## Supported versions

Security fixes land on `main`. We recommend running the latest commit from `main` or the most recent tagged release.
