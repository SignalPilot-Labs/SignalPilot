---
sidebar_position: 9
---

# REST API

Everything the web app does, it does through this API — so anything in the UI is
automatable. Around 210 routes, grouped below by area.

## Basics

- **Base URL** — your gateway: `http://localhost:3300` self-hosted,
  `https://gateway.signalpilot.ai` on Cloud.
- **Auth** — an API key as `Authorization: Bearer sp_…` or `X-API-Key: sp_…`. In
  cloud mode a Clerk session JWT is also accepted for browser calls.
- **Scope** — each route requires one of `read`, `query`, `write`, `execute`, or
  `admin`. See [Authentication](/docs/mcp/auth#scopes).
- **Tenancy** — the workspace is always derived from the credential, never from a
  parameter. There is no cross-workspace read.
- **Rate limits** — 10,000 req/min per IP general, 1,000/min on expensive routes,
  100/min on auth routes. MCP tool calls are limited separately
  (`SP_PER_KEY_RPM`, `SP_PER_ORG_RPM`).
- **Body size** — requests are capped at 2 MiB.

```bash
curl -H "X-API-Key: $SP_KEY" http://localhost:3300/api/connections
```

## Connections

| Route | Scope | Purpose |
|---|---|---|
| `GET /api/connections` · `POST /api/connections` | read · write | List, create |
| `GET·PUT·DELETE /api/connections/{name}` | read · write · write | Inspect, update, delete |
| `POST /api/connections/{name}/clone` | write | Copy a connection |
| `POST /api/connections/test-credentials` | write | Test before saving |
| `POST /api/connections/{name}/test` | read | Test an existing connection |
| `POST /api/connections/{name}/diagnose` | read | Connectivity diagnostics |
| `GET /api/connections/health` · `/{name}/health` · `/{name}/health/history` | read | Health and latency history |
| `GET /api/connections/stats` | read | Aggregate connection stats |
| `GET /api/connectors/capabilities` · `/api/connections/{name}/capabilities` | read | Tier and feature detection |
| `POST /api/connections/export` · `/import` | write | Portability |
| `POST /api/connections/parse-url` · `/validate-url` · `/build-url` | read | Connection-string helpers |
| `GET /api/network/info` | admin | Egress addresses for allowlisting |

## Schema

| Route | Scope | Purpose |
|---|---|---|
| `GET /api/connections/{name}/schema` · `/grouped` · `/compact` · `/enriched` | read | Schema in various shapes |
| `GET /api/connections/{name}/schema/ddl` | read | Reconstructed DDL |
| `GET /api/connections/{name}/schema/search` · `/filter` | read | Find tables and columns |
| `GET /api/connections/{name}/schema/link` | read | Natural language → tables |
| `GET /api/connections/{name}/schema/relationships` · `/join-paths` | read | FK map and join paths |
| `GET /api/connections/{name}/schema/samples` · `/sample-values` | read | Sample data |
| `POST /api/connections/{name}/schema/explore` · `/explore-columns` | read | Column-level exploration |
| `GET /api/connections/{name}/schema/overview` | read | Size and shape summary |
| `GET /api/connections/{name}/schema/diff` · `/diff/{compare}` · `/diff-history` | read | Drift between scans or connections |
| `GET /api/schema/changes` | read | Recent schema changes |
| `POST /api/connections/{name}/schema/refresh` · `/api/connections/schema/warmup` | write | Rescan |
| `GET /api/connections/{name}/schema/refresh-status` | read | Scan progress |
| `POST /api/connections/{name}/schema/refine` · `/correct-columns` | write | Corrections |
| `GET·PUT /api/connections/{name}/schema/endorsements` | read · write | Endorse trusted tables |
| `GET·PUT /api/connections/{name}/semantic-model` · `POST …/generate` | read · write | Semantic model |
| `GET /api/connections/{name}/schema/agent-context` | read | The bundle handed to an agent |

### Xata branches

| Route | Scope |
|---|---|
| `GET·POST /api/connections/{name}/xata/projects/{project}/branches` | read · write |
| `DELETE /api/connections/{name}/xata/projects/{project}/branches/{branch}` | write |
| `GET /api/connections/{name}/xata/branch-diff` | read |
| `GET /api/connections/{name}/xata/dbt-profile` | write |

## Query, governance and audit

| Route | Scope | Purpose |
|---|---|---|
| `POST /api/query` | query | Governed SQL |
| `POST /api/query/explain` | query | Plan without executing |
| `GET /api/audit` · `/api/audit/stats` | read | Audit trail and aggregates |
| `GET /api/audit/export` | admin | JSON/CSV compliance export |
| `POST·GET·DELETE /api/budget…` | write · read · write | Session budgets |
| `GET·PUT /api/connections/{name}/pii` | read · write | PII rules |
| `POST /api/connections/{name}/detect-pii` · `/detect-and-save-pii` | write | PII detection |
| `GET /api/connections/{name}/annotations` · `POST …/annotations/generate` | read · write | Table and column policy |
| `GET /api/cache/stats` · `POST /api/cache/invalidate` | read · write | Caches |
| `GET /api/schema-cache/stats` · `POST /api/schema-cache/invalidate` | read · write | Schema cache |
| `GET /api/pool/stats` | read | Connection pools |
| `GET /api/security/status` | — | Security posture summary |

## Knowledge base

| Route | Scope |
|---|---|
| `GET /api/knowledge` · `GET /api/knowledge/{id}` | read |
| `POST /api/knowledge` · `PUT·DELETE /api/knowledge/{id}` | admin |
| `POST /api/knowledge/{id}/approve` | admin |
| `GET /api/knowledge/{id}/edits` | read |
| `GET /api/knowledge/retrievals` · `/usage` | read |

## Evals

Covered in full, with semantics, in
[Running evals](/docs/evals/running#api-surface). All eval routes additionally
require platform-staff access and an allow-listed workspace.

## Projects, workspaces and notebooks

| Route | Scope |
|---|---|
| `GET·POST /api/projects` · `GET·PUT·DELETE /api/projects/{name}` | read · write |
| `POST /api/projects/{name}/scan` | write |
| `POST /api/dbt-cloud/projects` | admin |
| `GET·POST /api/workspace-projects` · `GET·PUT·DELETE /api/workspace-projects/{id}` | read · write |
| `GET /api/workspace-projects/{id}/clone-url` | read |
| `GET·DELETE /api/notebook-sessions/{id}` · `POST …/ping` | read · write · read |
| `GET /api/files/browse` | write |

## Sandboxes

| Route | Scope |
|---|---|
| `GET /api/sandboxes` · `GET /api/sandboxes/{id}` | read |
| `POST /api/sandboxes` · `DELETE /api/sandboxes/{id}` | execute |
| `POST /api/sandboxes/{id}/execute` | execute |

## Agents, chat and reports

| Route | Scope |
|---|---|
| `POST·GET /api/agent-runs` · `GET·PATCH /api/agent-runs/{id}` | write · read |
| `POST·GET /api/chat/conversations` · `…/{id}` · `…/{id}/messages` | write · read |
| `POST·GET /api/chat/traces/threads` · `…/{id}/events` | write · read |
| `GET /api/analysis-trails/resolve` | read |
| `GET /api/reports` · `GET /api/reports/{id}` | read |
| `POST·PATCH·DELETE /api/reports/{id}` | admin |

## Integrations

| Route | Scope |
|---|---|
| `GET /api/github/install-url` · `GET /api/github/installations` | write · read |
| `GET /api/github/installations/{id}/repos` | read |
| `POST·GET·DELETE /api/github/repo-links…` | write · read · write |
| `POST /api/github/sync/{project_id}` · `POST /api/github/fetch/{project_id}` | write · read |
| `POST /api/github/webhook` | — (HMAC-verified) |
| `POST /api/github/bot/scan` | admin |
| `GET /api/integrations/slack/oauth/start` · `/installations` | write · read |
| `POST /api/integrations/slack/oauth/{id}/provision` · `DELETE …/{id}` | write |
| `GET /api/integrations/notion/oauth/start` · `/installations` · `/{id}/pages` | write · read |
| `POST /api/integrations/notion/oauth/{id}/provision` · `DELETE …/{id}` | write |
| `GET·PUT·DELETE /api/integrations/notion/{name}` · `POST …/test` | read · write · read |

## Administration

| Route | Scope |
|---|---|
| `GET·POST·DELETE /api/keys…` | admin |
| `GET /api/plan` | read |
| `GET·PUT /api/settings` | admin |
| `GET·POST·DELETE /api/schema-watches…` · `POST …/{id}/run` | read · admin |
| `GET·PUT /api/org/secrets` | read · write |
| `GET /api/org/secrets/anthropic-key` | execute |
| `GET·PUT /api/user/secrets` | read · write |
| BYOK — see [BYOK](/docs/settings/byok#api) | admin |
| `GET·POST /api/demo/connector` | read · write |

## Operational endpoints

| Route | Notes |
|---|---|
| `GET /health` | Liveness only. Returns `{"status":"healthy"}` **without checking the database or pools** — do not use it as a readiness probe. |
| `GET /api/metrics` | An authenticated **SSE stream** of live metrics, not a Prometheus scrape target. Capped at 20 concurrent streams. |
| `GET /local-api-key` | Local mode only: hands the browser the local key. |

## Mounted sub-applications

Beyond the JSON API, the gateway mounts a git HTTP endpoint (workspace push and
pull), a notebook proxy, and a dbt proxy. The dbt proxy is the only consumer of
the `dbt_proxy` scope.
