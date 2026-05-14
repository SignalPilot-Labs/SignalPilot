# SignalPilot Workspaces — Architecture

Round 1 design document. Covers the full product; later rounds fill in implementation detail.

---

## 1. Overview

Workspaces adds a governed Claude Code agent product on top of the SignalPilot gateway. Users describe a data task in plain language; an agent runs in a gVisor sandbox, calls SignalPilot MCP tools (SQL execution, schema introspection, dbt helpers), generates ECharts dashboard specs, and runs dbt models — all without touching raw credentials.

The key design constraint: **the sandbox never sees database passwords, API keys, or SSH private keys.** The gateway owns all credentials; the sandbox communicates through governed MCP tool calls and a short-lived run-scoped dbt-proxy token.

Workspaces operates in two deployment modes:
- **`SP_DEPLOYMENT_MODE=local`** — inference token comes from `CLAUDE_CODE_OAUTH_TOKEN` on the host; no dependency on `signalpilot-backend`. Works fully standalone.
- **`SP_DEPLOYMENT_MODE=cloud`** — inference token is the user's Anthropic API key (stored via `gateway/byok/`) or a metered proxy token from `signalpilot-backend`. Requires `signalpilot-backend` only for the metered path.

---

## 2. Component Diagram

```
            signalpilot/web (Next.js)
              /workspaces/* routes (R5)
                       | HTTPS (Clerk)
                       v
            workspaces/api (FastAPI)
              prompt / run / events / approve / CRUD
                 |  spawn              |  persist
                 v                     v
        workspaces/agent (gVisor)   Postgres (schema: workspaces)
          server.py + Claude SDK
          + SP skills (baked from plugin/)
          + SP MCP client
                 |  MCP streamable-http    +----------------+
                 |  + dbt -> localhost:N   |   user DB      |
                 v                         |   (warehouse)  |
        signalpilot/gateway                +-------^--------+
          MCP tools (discover at runtime)          |
          connector pool (creds here)              |
          SSH tunnel manager  ─────────────────────+
          dbt-proxy listener (NEW, R3)
```

Prompt flow: web sends prompt to workspaces-api, which spawns a fresh sandbox container. The agent runs a Claude Code SDK session with the baked `CLAUDE.md`, calls SP MCP tools (authenticated by a per-run gateway key), optionally calls `dbt run` via the dbt-proxy, and streams events over SSE. Approval gates pause execution for tools tagged `requires_approval: true`.

---

## 3. Credential Isolation

**Goal:** the sandbox never receives `password=`, `account=`, private keys, or AWS secrets. But `dbt run` must work end-to-end.

### Interface contract (locked in Round 1)

1. The gateway gains a new module `gateway/dbt_proxy/` (Round 3) that opens a TCP listener on an ephemeral host port, one per active run.
2. The listener authenticates by a **short-lived run-scoped token** — HMAC of `run_id + connector_id`, TTL = run lifetime. Not a database password.
3. workspaces-api injects into the sandbox **only**: `host_port`, `run_token`, and schema/database/role names. It writes `~/.dbt/profiles.yml` with `host: host.containers.internal`, `port: <host_port>`, `user: run-<run_id>`, `password: <run_token>`. No real credential crosses the boundary.
4. The proxy translates incoming connections to outbound calls through the gateway's existing `connectors/pool_manager.py` (real credentials via `byok/`). DDL/DML governance from `gateway/governance/` runs on every statement.
5. SSH tunnels: the gateway's `connectors/ssh_tunnel.py` is invoked by `pool_manager` at connector-open time. The proxy sits on top of the pool — the sandbox sees only `host.containers.internal:<host_port>`.
6. MCP: workspaces-api mints a gateway API key per run, scoped to the user's connectors. The key authenticates the run, not the user.

### Wire format choice — deferred to Round 3

Two candidates under consideration. Round 3 picks based on `pool_manager.py` shape and protocol coverage.

**Option A — Wire-protocol proxy:** speak Postgres-wire or Snowflake-REST natively inside the proxy. dbt connects believing it is talking directly to the warehouse. Heavy to implement (one protocol class per warehouse family); fully transparent to dbt and any adapter version.

**Option B — dbt adapter shim:** ship a custom dbt adapter inside the sandbox that makes HTTP calls to the gateway (similar to the MCP pattern). No wire-protocol implementation; reuses the existing MCP auth layer. Requires installing the shim in every sandbox image and maintaining dbt adapter version compatibility.

Round 1 documents both options without choosing.

---

## 4. Auth and Inference

| Mode (`SP_DEPLOYMENT_MODE`) | Inference token source | Where set | Where injected |
|---|---|---|---|
| `local` | `CLAUDE_CODE_OAUTH_TOKEN` env on host | host shell / `.env` | passed by workspaces-api to sandbox env at spawn (never logged) |
| `cloud` + BYO | User's Anthropic API key, stored encrypted via `gateway/byok/` | web settings `/workspaces/settings/inference` | minted per-run as `ANTHROPIC_API_KEY` in sandbox env |
| `cloud` + metered | `signalpilot-backend` issues a short-lived inference proxy token | settings toggle; flag `WORKSPACES_METERED_INFERENCE_ENABLED` | `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` in sandbox env |

**Hard rule:** workspaces-api must refuse to spawn a run if no inference source is configured. No silent fallback. Error message: "Configure CLAUDE_CODE_OAUTH_TOKEN (local) or an inference source in Settings (cloud)."

We use `CLAUDE_CODE_OAUTH_TOKEN` because that is the env the `claude_agent_sdk` package reads at import. A different name would silently 401 inside the container.

`signalpilot-backend` is only a dependency for `cloud` + metered. `SP_DEPLOYMENT_MODE=local` works entirely standalone.

---

## 5. Charting Stack

**Apache ECharts** via `echarts-for-react`.

Rationale over alternatives:
- Recharts (already in `signalpilot/web/`): not suitable for Workspaces dashboards — performance degrades above ~10k rows; no WebGL renderer; limited progressive rendering.
- ECharts: `large: true` mode, WebGL renderer, `dataset` component, and progressive rendering handle 100k+ row result sets. Full chart matrix (scatter, candlestick, graph, geo, heatmap) in one library. Themeable to match the SignalPilot design system.
- visx/Plot/Vega-Lite: theming friction or bundle-size cost not justified.

ECharts lives in `workspaces/dashboards/` only. The existing `signalpilot/web/` charts (Recharts wrappers in `components/ui/data-viz`) are untouched.

---

## 6. Web Placement

Workspaces UI extends the existing `signalpilot/web/` Next.js app. New pages live at `signalpilot/web/app/workspaces/` (introduced in Round 5). There is no separate `workspaces/web/` directory.

The existing `app/projects/` (dbt project management) and `app/sandboxes/` (sandbox VM listing) routes are not modified — Workspaces introduces its own `/workspaces/` routes that provide the agent chat, ECharts dashboard editor, and dbt project selector.

---

## 7. Dashboards Data Model

All tables in Postgres schema `workspaces`. ORM choice in Round 3 (likely SQLAlchemy 2.0 async, matching the gateway).

**`dashboard`**
- `id`, `workspace_id`, `name`
- `layout_json` — react-grid-layout shape
- `created_at`, `updated_at`, `created_by`

**`chart`**
- `id`, `dashboard_id`, `title`, `chart_type`
- `echarts_option_json` — full ECharts `option` object persisted by the agent
- `query_id` — foreign key to `chart_query`
- `position`, `created_at`

**`chart_query`**
- `id`, `chart_id`, `connector_id` — references user's gateway connector
- `sql`, `params_json`
- `refresh_interval_seconds`

**`chart_cache`**
- `query_id`, `params_hash`
- `result_arrow_bytes` — `bytea` Arrow IPC payload
- `computed_at`, `expires_at`

Migrations and ORM models are deferred to Round 3. Round 1 only documents this schema.

---

## 8. dbt Project Link Modes

Three supported modes for connecting a dbt project to a Workspace:

**1. dbt Cloud link**
OAuth flow: user grants access → gateway stores `account_id`, `project_id`, encrypted refresh token. Agent triggers `dbt run` via dbt Cloud Jobs API. No local clone needed.

**2. GitHub link**
GitHub App install → gateway clones into `workspaces-data` volume on demand. Webhook on push triggers pull. Agent runs `dbt run` locally against the checkout, via dbt-proxy.

**3. Native upload**
User uploads a tarball. Extracted into `workspaces-data` volume. No sync — user re-uploads on change.

Volume `workspaces-data` contains all clones and uploads. On-disk layout is defined in Round 4.

---

## 9. Multi-Round Delivery Plan

- **R1 (this)** — Scaffolding: `workspaces/` directory layout, vendored AutoFyn sandbox (trimmed), `CLAUDE.md`, pricing framework, this architecture doc.
- **R2** — workspaces-api FastAPI: routes for prompt/run/events/approve. Postgres schema `workspaces.run`, `workspaces.run_event`, `workspaces.approval`. Sandbox spawn logic.
- **R3** — Gateway `dbt_proxy/` module + run-token auth + wire-format pick. Schema migrations for dashboards. `SP_DEPLOYMENT_MODE`-aware inference selection in workspaces-api.
- **R4** — dbt link adapters: Cloud OAuth, GitHub App, native upload. Sync jobs. `workspaces-data` volume layout.
- **R5** — Web UI: `signalpilot/web/app/workspaces/` — chat interface, ECharts dashboard editor, dbt project selector, settings page.
- **R6** — Approval flow end-to-end. SSE event streaming smoke test. Smoke-test agent run that creates one chart.
- **R7** — Docker Compose service: `workspaces-api` + sandbox image. Local-mode demo. Fix Dockerfile build context; populate `plugin/` if empty.
- **R8** — Hardening: governance integration tests, credential-isolation negative tests, performance, public docs.
