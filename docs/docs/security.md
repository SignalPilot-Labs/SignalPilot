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
- **API keys** with Fernet encryption at rest, org-scoped, with brute-force rate limiting (60/min/IP)
- **Org role enforcement**: Admin-only endpoints require `org:admin` role

## Network

- **SSRF protection**: Cloud warehouse connection parameters validated against allowed domains (Snowflake, Databricks, BigQuery)
- **DNS rebinding defense**: Hostnames resolved and validated before connection
- **Non-root containers**: Gateway and backend run as UID 10001

## Sandboxed Workspaces

- **gVisor isolation**: Notebook pods (`run_notebook`) execute under the gVisor runtime, not a shared host kernel.
- **Per-org NetworkPolicy**: Each org's notebook pods are network-isolated from other tenants' workloads.
- **Read-only rootfs**: Pod root filesystem is mounted read-only.
- **IMDS egress blocked**: Access to the cloud instance metadata service is denied from inside the pod.

## Evaluation workloads

- Eval configuration, execution, evidence, and live-sandbox routes require a user ID listed in `SP_ADMIN_USER_IDS` and an org listed in `SP_EVAL_ALLOWED_ORGS`.
- Every task receives a short-lived API key bound to one run, one task, and one database connection. The key cannot access query history, workspace integrations, notebooks, connection mutation, or Xata branch-control tools.
- Write tasks receive a disposable branch credential. The local Postgres provider refuses to start a task while its role can connect to any other non-template database.
- Eval pods run non-root with a read-only root filesystem, all Linux capabilities dropped, no service-account token, resource limits, and mandatory NetworkPolicy in cloud mode.
- The local eval runtime cannot join the control database or object-store networks. It receives artifacts through a signed, GET/HEAD-only proxy and uses a dedicated disposable warehouse service.

Eval containers execute model-authored commands and hold the task's source checkout and branch credential. The current cloud policy permits public HTTPS so the agent can reach its model provider. Deployments that treat eval repositories as hostile must route that egress through an allowlisting proxy; Kubernetes NetworkPolicy alone cannot restrict destinations by hostname.

## Audit

- **Every query logged** with timestamp, org, user, connection, and SQL
- **PII redaction**: SQL string literals replaced with `<REDACTED>` in audit logs
- **Query cost estimation** before execution

## Encryption

- **Fernet with MultiFernet rotation** for credential storage; prior keys are decrypt-only and rows are rewritten under the primary key on access

## Rate limiting

- 100 requests/min/IP on auth endpoints (brute-force protection); 60 *failed* authentications/min/IP
- 1000 MCP tool calls/min/API key (`SP_PER_KEY_RPM`)
- 5000 MCP tool calls/min/org, cloud mode (`SP_PER_ORG_RPM`)
- 10000 requests/min/IP general, 1000/min on expensive endpoints

## Tenant isolation

In multi-tenant (cloud) mode, every API key is scoped to an org. A key can only access connections registered by that org. Cross-tenant access is blocked at the data layer — not just at the API layer.

## Supported versions

Security fixes land on `main`. We recommend running the latest commit from `main` or the most recent tagged release.
