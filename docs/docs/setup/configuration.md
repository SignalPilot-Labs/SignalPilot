---
sidebar_position: 3
---

# Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and set your values before starting the stack.

This page covers the operator-facing surface. Variables not listed here are internal implementation detail and are not part of the supported configuration.

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection URL for the gateway's own state (connections, knowledge base, runs, audit). Required in cloud and in the Docker Compose stack. |
| `LOG_LEVEL` | `info` | Log verbosity for the gateway process. |

## Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_DATA_DIR` | `~/.signalpilot` | Path to the directory where the gateway stores its SQLite database, encryption salt, annotations, and local state. Override per-deployment (e.g. `/var/lib/signalpilot`). |

## Encryption

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_ENCRYPTION_KEY` | — | Required in cloud mode. Primary raw Fernet key or passphrase used for credential encryption. |
| `SP_ENCRYPTION_SALT` | — | Required in cloud mode only when `SP_ENCRYPTION_KEY` is a passphrase. Preserve it across deployments. |
| `SP_ENCRYPTION_KEY_OLD` | — | Comma-separated prior Fernet keys used only during explicit key rotation. Remove each key after all credentials have been read and rewritten under the primary key. |
| `SP_BYOK_PROVIDER` | — | BYOK encryption provider name (e.g. `aws_kms`). Pro/Team/Enterprise plans only. |
| `SP_BYOK_PROVIDER_CONFIG` | — | JSON-encoded configuration for the BYOK provider. |

SignalPilot does not read ciphertext produced by retired pre-PBKDF2 key derivations.
Before upgrading from a release that used one of those formats, run that release,
rotate every credential to a current Fernet key, and verify that no credential is
pending rotation. An in-place upgrade with unmigrated ciphertext fails closed.

## Network

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_GATEWAY_URL` | `http://localhost:3300` | Public URL of this gateway instance. Used for internal service-to-service callbacks and embedded in MCP tool responses. Override when reverse-proxying or hosting at a non-default port. |
| `SP_SANDBOX_MANAGER_URL` | — | URL of the sandbox manager service (DuckDB/SQLite sandboxed execution). Required when using sandbox-backed connectors. |
| `SP_GATEWAY_CSP_POLICY` | — | Override the default `Content-Security-Policy` header. Leave unset to use the built-in policy. |
| `SP_BACKEND_URL` | — | URL of the SignalPilot backend API (cloud deployments only). |
| `SP_ALLOWED_ORIGINS` | — | Comma-separated list of allowed CORS origins. |
| `SP_MCP_PORT` | `8000` | Port the MCP server listens on (only used when `SP_MCP_TRANSPORT=streamable-http`). |
| `SP_MCP_TRANSPORT` | `stdio` | MCP transport protocol. Valid values: `stdio`, `streamable-http`. |

## Deployment

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_DEPLOYMENT_MODE` | `local` | Set to `cloud` to enable multi-tenant plan enforcement, SSRF validation for TCP connections, and Clerk JWT authentication. |

## Rate limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_PER_KEY_RPM` | `1000` | MCP tool calls per minute per API key. |
| `SP_PER_ORG_RPM` | `5000` | MCP tool calls per minute per org (cloud mode). |

## Auth

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_JWT_LEEWAY` | `30` | Clock leeway in seconds for JWT verification. |
| `SP_SANDBOX_TOKEN` | — | Shared secret used to authenticate gateway-to-sandbox-manager requests. |
| `CLERK_PUBLISHABLE_KEY` | — | Clerk publishable key. The JWKS endpoint is derived from it. Cloud mode only. |
| `CLERK_JWT_AUDIENCE` | — | Expected `aud` claim on Clerk session tokens. Empty skips the audience check. |
| `SP_EXPECTED_AZP` | — | Expected authorized party (`azp`) on Clerk tokens — the origin your frontend is served from. Empty skips the check. |
| `SP_SESSION_JWT_SECRET` | — | Secret used to sign gateway-issued session tokens (notebooks, sandboxes). **Required in cloud mode** — the gateway refuses to boot without it. In local mode it is generated once and persisted to the gateway-private secrets volume. |
| `SP_SESSION_JWT_TTL_SECONDS` | `28800` | Lifetime of a gateway-issued session token. |

## Governance

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_MAX_EXPORT_ROWS` | `50000` | Maximum rows allowed in a single audit export. |
| `SP_ANNOTATIONS_TTL` | `60.0` | Cache TTL in seconds for schema annotation files. |
| `SP_ADMIN_USER_IDS` | `local` | Comma-separated platform-staff user IDs with access to security administration and eval operations. Set this explicitly in cloud; an unset cloud deployment fails closed on eval routes. The value `local` is the single-user local-deployment sentinel. |

## SSRF protection

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_ALLOW_PRIVATE_CONNECTIONS` | — | Set to `true` to allow TCP connections to RFC1918 private ranges (loopback and link-local are always blocked). Intended for self-hosted deployments where the warehouse is on a private network. Unset by default in cloud mode. |
| `SP_MCP_ALLOWED_HOSTS` | — | Comma-separated hostnames accepted on the MCP endpoint's `Host` header. Empty accepts any host. |

## Workspaces, notebooks and sandboxes

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_SANDBOX_ENABLED` | `false` | Enable sandboxed execution (DuckDB/SQLite) via the sandbox manager. |
| `SP_DISABLE_SANDBOX` | — | Kill switch for sandboxed execution. Setting it in cloud mode is a configuration violation and is reported at startup. |
| `SP_WORKSPACE_ROOT` | — | Root directory for workspace files. `SP_NOTEBOOK_ROOT` is accepted as an alias. |
| `SP_REPOS_DIR` | `/repos` | Where the gateway checks out project repositories. |
| `SP_FILE_BROWSE_ROOT` | — | Root the file browser is confined to. |
| `SP_GIT_MAX_PUSH_BYTES` | `524288000` (500 MiB) | Ceiling on a single push from a workspace. |
| `SP_NOTEBOOK_IMAGE` | `signalpilot-notebook:latest` | Notebook image. Must be digest-pinned in cloud mode. |
| `SP_NOTEBOOK_IDLE_TIMEOUT` | `7200` | Seconds before an idle notebook session is reaped. |
| `SP_NOTEBOOK_START_TIMEOUT_SECONDS` | `90` | How long to wait for a notebook session to become ready. |
| `SP_NOTEBOOK_TOKEN` / `SP_NOTEBOOK_TOKEN_FILE` | — | Shared token for gateway-to-notebook calls, inline or read from a file. |
| `SP_NOTEBOOK_DIRECT_URL` | — | Bypass URL for reaching a notebook directly, for local development. |

## Kubernetes (cloud)

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_K8S_NAMESPACE` | `default` | Namespace the gateway operates in when no tenant namespace applies. |
| `SP_K8S_HOST` / `KUBECONFIG` | — | API server address, or a kubeconfig path. In-cluster credentials are used when neither is set. |
| `SP_GATEWAY_NAMESPACE` | `signalpilot` | Namespace the gateway itself runs in. |
| `SP_GATEWAY_POD_SELECTOR` | `app=signalpilot-gateway` | Label selector identifying gateway pods. |
| `SP_GATEWAY_SERVICE_ACCOUNT` | `signalpilot-gateway` | Service account the gateway runs as. |
| `SP_GATEWAY_RUNTIME_GROUPS` | — | Extra Kubernetes groups the gateway's runtime identity belongs to (comma-separated). `system:` groups are rejected. |
| `SP_NOTEBOOK_NAMESPACE_PREFIX` | `sp-nb` | Prefix for per-org tenant namespaces. |
| `SP_NOTEBOOK_NETWORK_POLICY` | `true` | Set to `false` only where the cluster genuinely has no policy controller. Eval pods refuse to start when policy enforcement is off. |
| `SP_NOTEBOOK_EGRESS_CIDR` | — | Extra egress CIDR (e.g. object storage) allowed out of tenant namespaces. Validated as an IP network. |
| `SP_NOTEBOOK_RUNTIME_CLASS` | — | RuntimeClass for tenant pods — set to your sandboxed runtime (e.g. gVisor). |
| `SP_NOTEBOOK_NODE_LABEL_KEY` / `SP_NOTEBOOK_NODE_LABEL_VALUE` | `signalpilot.ai/notebook` / — | Node selector pinning tenant pods to the sandbox node group. |
| `SP_NOTEBOOK_PVC` | — | PersistentVolumeClaim mounted as the workspace. Unset means ephemeral storage. |
| `SP_NOTEBOOK_UPSTREAM_MODE` | `nodeport` | How the gateway reaches notebook pods. |
| `SP_PUBLIC_GATEWAY_URL` / `SP_PUBLIC_GATEWAY_PORT` | local default / `3300` | Address tenant pods use to call the gateway back. |

## GitHub App

Required to clone private repositories — project repos, and private eval sets.

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_GITHUB_APP_ID` | — | GitHub App id. |
| `SP_GITHUB_APP_CLIENT_ID` / `SP_GITHUB_APP_CLIENT_SECRET` | — | OAuth credentials for the install flow. |
| `SP_GITHUB_APP_PRIVATE_KEY` | — | App private key (PEM) used to mint short-lived installation tokens. |
| `SP_GITHUB_APP_SLUG` | `signalpilot` | App slug, used to build install URLs. |
| `SP_WEB_URL` | `http://localhost:3200` | Public URL of the web app, for OAuth redirects. |

## Notion

| Variable | Default | Description |
|----------|---------|-------------|
| `NOTION_OAUTH_CLIENT_ID` / `NOTION_OAUTH_CLIENT_SECRET` | — | Notion integration credentials. Required for the Notion connect flow. |
| `NOTION_OAUTH_REDIRECT_URI` | — | Redirect URI registered with the integration. |
| `NOTION_WEBHOOK_VERIFICATION_TOKEN` | — | Verification token for Notion webhooks. |
| `NOTION_DASHBOARD_MAX_BYTES` | — | Ceiling on a dashboard payload written to Notion. |

## Evals

The eval harness has its own configuration surface — runner image, evidence
store, branch provider, quotas, and notifications. See
[Deploying the harness](../evals/deploying.mdx#environment-variables) for the
full list.

---

**Knobs that are not env-driven:**

- **LIMIT injection default** — `query_database` accepts a `row_limit` parameter (default `1000`, max `10000`). There is no global env override; callers control the per-call limit.
- **Budget caps** — set per session via the `start_session`/`check_budget` MCP tools. There is no global default budget env var.
- **Audit log** — always enabled; every query is logged. There is no env toggle.
- **PII redaction in audit** — always active; SQL string literals are replaced with `<REDACTED>` in audit records.
