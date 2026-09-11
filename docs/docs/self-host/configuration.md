---
sidebar_position: 2
title: Configuration reference
sidebar_label: Configuration reference
---

# Configuration reference

All configuration is through environment variables. Copy `.env.example` to `.env` and set your values before you start the stack. The local stack runs with no changes; every variable below has a working default or is only needed in cloud mode.

**Required** means the gateway will not start without it. **Cloud-required** means it is only required when `SP_DEPLOYMENT_MODE=cloud`. Variables not listed here are internal and not part of the supported configuration surface.

## Core

| Variable | Default | What it does |
|---|---|---|
| `SP_DEPLOYMENT_MODE` | `local` | `local` or `cloud`. Cloud mode turns on multi-tenant plan enforcement, Clerk sign-in, and the startup hardening checks described in [Run in production](/docs/self-host/production). |
| `LOG_LEVEL` | `info` | Log verbosity for the gateway and worker. |
| `SP_DATA_DIR` | `~/.signalpilot` | Directory for the encryption salt, schema annotations, and the local development API key. |
| `SP_GATEWAY_URL` | `http://localhost:3300` | URL of this gateway as browsers and clients reach it. Set it when you reverse-proxy or change the port. |
| `SP_PUBLIC_GATEWAY_URL` | `http://gateway:3300` | **Cloud-required.** URL that sandboxes use to call the gateway back. The local default is rejected in cloud mode. |
| `SP_PUBLIC_GATEWAY_PORT` | `3300` | Port that goes with `SP_PUBLIC_GATEWAY_URL`. |
| `SP_WEB_URL` | `http://localhost:3200` | Public URL of the web app, used for OAuth redirects. |
| `SP_PUBLIC_URL` | unset | Public URL of the whole deployment when it differs from `SP_GATEWAY_URL`. |

## Database

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | unset | **Required.** Postgres connection URL for the gateway's own state, in the form `postgresql+asyncpg://user:pass@host:5432/db`. The Compose stack sets it for you. |
| `SP_DB_POOL_MAX_CONNECTIONS` | `5` | Connection pool size per warehouse connection, from 1 to 20. |
| `SP_DB_POOL_ACQUIRE_TIMEOUT_SECONDS` | `30` | How long a query waits for a pooled connection before it fails. |

## Auth and encryption

| Variable | Default | What it does |
|---|---|---|
| `SP_ENCRYPTION_KEY` | generated locally | **Cloud-required.** Fernet key or passphrase that encrypts stored warehouse credentials. The Compose file ships a public example value. Replace it before you store real credentials. |
| `SP_ENCRYPTION_SALT` | unset | Salt used when `SP_ENCRYPTION_KEY` is a passphrase. Keep it with the key; a different salt derives a different key. |
| `SP_ENCRYPTION_KEY_OLD` | unset | Comma-separated retired keys. They decrypt only. Rows are re-encrypted under the current key as they are read. See [key rotation](/docs/self-host/production#secrets-and-key-rotation). |
| `SP_SESSION_JWT_SECRET` | generated locally | **Cloud-required.** Signs the session tokens the gateway issues to notebooks and sandboxes. Local mode generates one and keeps it in the `signalpilot-gateway-secrets` volume. |
| `SP_SESSION_JWT_TTL_SECONDS` | `28800` | Lifetime of a gateway-issued session token. |
| `SP_JWT_LEEWAY` | `30` | Allowed clock skew, in seconds, when verifying tokens. |
| `CLERK_PUBLISHABLE_KEY` | unset | **Cloud-required.** Clerk publishable key. The JWKS endpoint is derived from it. |
| `CLERK_SECRET_KEY` | unset | **Cloud-required.** Clerk secret key. |
| `CLERK_JWT_AUDIENCE` | unset | Expected `aud` claim on Clerk tokens. Leave unset unless your Clerk JWT template emits one. |
| `SP_EXPECTED_AZP` | unset | Comma-separated origins allowed in the `azp` claim, for example `https://app.your-domain.example`. Recommended in cloud mode. |
| `SP_ADMIN_USER_IDS` | `local` | **Cloud-required.** Comma-separated user ids that count as platform admins for security administration and eval routes. `local` is the single-user sentinel for local mode. |
| `SP_ORG_ID` | `local` | Organization id used in local mode. |
| `SP_BACKEND_URL` | unset | URL of a separate backend API. When set, every MCP request must carry an `sp_` API key. |

The gateway no longer reads ciphertext produced by retired pre-PBKDF2 key derivations. If you are upgrading from a very old release, rotate every credential on that release first.

## BYOK

| Variable | Default | What it does |
|---|---|---|
| `SP_BYOK_PROVIDER` | `local` | Encryption provider for [bring-your-own-key](/docs/settings/byok) plans. |
| `SP_BYOK_PROVIDER_CONFIG` | unset | JSON configuration for the provider. |
| `SP_BYOK_ALLOW_CUSTOM_ENDPOINT` | `true` locally, `false` in cloud | Allow a custom key-service endpoint, for testing. |

## Network and limits

| Variable | Default | What it does |
|---|---|---|
| `SP_ALLOWED_ORIGINS` | unset | **Cloud-required.** Comma-separated CORS origins. In cloud mode every entry must be `https://` or a loopback address, and wildcards are refused. |
| `SP_GATEWAY_CSP_POLICY` | built-in policy | Override the `Content-Security-Policy` header. |
| `SP_ALLOW_PRIVATE_CONNECTIONS` | unset | Set to `true` to allow warehouse connections into private address ranges. Loopback and link-local stay blocked. Meant for self-hosted gateways on the same network as the warehouse. |
| `SP_PER_KEY_RPM` | `1000` | MCP tool calls per minute per API key. |
| `SP_PER_ORG_RPM` | `5000` | MCP tool calls per minute per organization, cloud mode. |
| `SP_MAX_EXPORT_ROWS` | `50000` | Maximum rows in one audit export. |
| `SP_ANNOTATIONS_TTL` | `60` | Cache lifetime, in seconds, for schema annotation files. |
| `SP_GIT_MAX_PUSH_BYTES` | `524288000` | Ceiling on a single push from a workspace (500 MiB). |

## MCP

| Variable | Default | What it does |
|---|---|---|
| `SP_MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http`. The Compose stack uses `streamable-http`. |
| `SP_MCP_PORT` | `8000` | Port for the standalone MCP server when the transport is `streamable-http`. |
| `SP_MCP_ALLOWED_HOSTS` | unset | Comma-separated hostnames accepted in the `Host` header on `/mcp`. Empty accepts any host. |
| `SP_MCP_OAUTH_DISABLED` | `false` | Turn off OAuth sign-in on `/mcp`, leaving API keys as the only method. |
| `SP_MCP_OAUTH_RESOURCE_URL` | derived | The resource identifier advertised to OAuth clients. |
| `SP_MCP_OAUTH_REQUIRE_AUDIENCE` | `true` | Require OAuth access tokens to name this gateway in their audience. |
| `SP_MCP_OAUTH_PUBLIC_URL` | `SP_GATEWAY_URL` | Public URL used in OAuth metadata when it differs from the gateway URL. |

## Storage

| Variable | Default | What it does |
|---|---|---|
| `SP_WORKSPACE_ROOT` | unset | Root directory for workspace files. |
| `SP_REPOS_DIR` | `/repos` | Where the gateway checks out project repositories. |
| `SP_FILE_BROWSE_ROOT` | unset | Directory the file browser is confined to. |
| `SP_WORKSPACE_S3_BUCKET` | unset | Bucket for workspace files. |
| `SP_WORKSPACE_S3_ENDPOINT`, `SP_WORKSPACE_S3_REGION`, `SP_WORKSPACE_S3_ACCESS_KEY`, `SP_WORKSPACE_S3_SECRET_KEY` | unset | Endpoint, region, and credentials for the workspace bucket. Any S3-compatible service works; the local stack uses MinIO. |
| `SP_CHAT_OBJECTS_BUCKET` | unset | Bucket for chat artifacts. |
| `SP_CHAT_OBJECTS_S3_ENDPOINT`, `SP_CHAT_OBJECTS_S3_REGION`, `SP_CHAT_OBJECTS_S3_ACCESS_KEY`, `SP_CHAT_OBJECTS_S3_SECRET_KEY` | unset | Endpoint, region, and credentials for the chat artifacts bucket. |

## Notebooks and sandboxes

| Variable | Default | What it does |
|---|---|---|
| `SP_NOTEBOOK_EXECUTION_BACKEND` | `""` | Which backend runs notebook and chat sessions. Empty picks by environment: `direct` when `SP_NOTEBOOK_DIRECT_URL` is set, otherwise the hosted sandbox backend. `direct` uses one shared notebook container. `vercel` selects the hosted sandbox backend. |
| `SP_NOTEBOOK_DIRECT_URL` | unset | URL of the shared notebook container. Local mode only. Any value is refused in cloud mode. |
| `SP_NOTEBOOK_VERCEL_IMAGE` | unset | Image for hosted sandboxes. Must be a digest reference (`@sha256:...`) in cloud mode. |
| `SP_NOTEBOOK_TOKEN`, `SP_NOTEBOOK_TOKEN_FILE` | generated locally | Shared token for gateway-to-notebook calls, inline or read from a file. |
| `SP_NOTEBOOK_SESSION_GRANT_SECONDS` | `1800` | Lifetime of the session grant handed to a sandbox. |
| `SP_NOTEBOOK_IDLE_SNAPSHOT_SECONDS` | `900` | Idle time before a session is snapshotted and its sandbox destroyed. |
| `SP_NOTEBOOK_SNAPSHOT_EXPIRATION_SECONDS` | `604800` | How long a snapshot can be resumed from (7 days). |
| `SP_NOTEBOOK_START_TIMEOUT_SECONDS` | `90` | How long to wait for a sandbox to become ready. |
| `SP_NOTEBOOK_VCPUS` | `2` | CPUs per sandbox. |
| `SP_NOTEBOOK_MEMORY_MB` | `4096` | Memory per sandbox. |
| `SP_NOTEBOOK_EGRESS_ALLOW` | unset | Comma-separated hosts a sandbox may reach in addition to DNS and the gateway. |
| `SP_NOTEBOOK_MAX_RUNNING_PER_ORG` | `20` | Maximum running sandboxes per organization. |
| `SP_SANDBOX_ENABLED` | `false` | Enable sandboxed DuckDB and SQLite execution over local files through the sandbox manager. |
| `SP_DISABLE_SANDBOX` | unset | Kill switch for sandboxed execution. Refused in cloud mode. |
| `SP_SANDBOX_MANAGER_URL` | `http://localhost:8180` | URL of the sandbox manager service. |
| `SP_SANDBOX_TOKEN` | unset | Shared secret between the gateway and the sandbox manager. |

## Chat and agent

| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Anthropic API key for chat and agent runs. |
| `CLAUDE_CODE_OAUTH_TOKEN` | unset | Alternative credential for chat and agent runs. |
| `SP_CHAT_AGENT_MODEL` | provider default | Model used by the chat agent. |
| `SP_CHAT_DATASET_CONNECTORS` | `postgres,snowflake` | Connector types that expose dataset references in chat. |
| `SP_CHAT_APPROVAL_WARM_SECONDS` | `900` | How long a sandbox stays warm while a query approval is pending. |
| `SP_AGENT_EFFORT` | `medium` | Reasoning effort for agent runs. |
| `SP_AGENT_MAX_CONCURRENT_PER_ORG` | `2` | Concurrent agent runs per organization. |
| `CHAT_WORKER_CONCURRENCY` | `4` | Runs one worker process handles at once. |
| `CHAT_WORKER_LEASE_SECONDS` | `45` | Lease a worker holds on a run before another worker may claim it. |
| `CHAT_WORKER_POLL_SECONDS` | `1.0` | How often a worker polls for new runs. |
| `SIGNALPILOT_DELIVERY_MODEL` | provider default | Model used for delivery flows such as Slack and Notion. |

Feature flags. Each accepts `true` or `false`:

| Variable | Default | What it does |
|---|---|---|
| `SP_FEATURE_STANDALONE_CHAT` | unset | Enable the standalone chat page. |
| `SP_FEATURE_MCP_AGENT` | `true` | Expose the agent tools over MCP. |
| `SP_FEATURE_CHAT_QUERY_APPROVAL` | unset | Ask before the agent runs a query. |
| `SP_FEATURE_CHAT_STRUCTURED_RESULTS` | unset | Return structured results in chat. |
| `SP_FEATURE_CHAT_SIZE_ROUTER` | unset | Route large results through the size router. |
| `SP_FEATURE_CHAT_RUNTIME_RESULTS` | unset | Show runtime query results in the chat panel. |
| `SP_FEATURE_CHAT_RUNTIME_ARTIFACTS` | unset | Capture files the agent writes as chat artifacts. |
| `SP_FEATURE_CHAT_DATASET_REFS` | unset | Let chats reference saved datasets. |
| `SP_FEATURE_CHAT_ORG_SHARING` | unset | Allow sharing chats across the organization. |
| `SP_FEATURE_CHAT_FORKING` | unset | Allow forking a chat. |

## Integrations

| Variable | Default | What it does |
|---|---|---|
| `SP_GITHUB_APP_ID` | unset | GitHub App id. Needed to clone private project and eval repositories. |
| `SP_GITHUB_APP_CLIENT_ID`, `SP_GITHUB_APP_CLIENT_SECRET` | unset | OAuth credentials for the GitHub install flow. |
| `SP_GITHUB_APP_PRIVATE_KEY` | unset | App private key (PEM) used to mint short-lived installation tokens. |
| `SP_GITHUB_APP_SLUG` | `signalpilot` | App slug, used to build install URLs. |
| `SP_GITHUB_BOT_TOKEN` | unset | Token used to comment on pull requests and set statuses when no App is configured. |
| `SP_GITHUB_WEBHOOK_SECRET` | unset | HMAC secret for `/api/github/webhook`. |
| `SP_GITHUB_BOT_CONNECTION` | unset | Default connection the pull request verification battery runs against. |
| `NOTION_OAUTH_CLIENT_ID`, `NOTION_OAUTH_CLIENT_SECRET` | unset | Notion integration credentials. |
| `NOTION_OAUTH_REDIRECT_URI` | unset | Redirect URI registered with the Notion integration. |
| `NOTION_WEBHOOK_VERIFICATION_TOKEN` | unset | Verification token for Notion webhooks. |
| `NOTION_DASHBOARD_MAX_BYTES` | unset | Ceiling on a dashboard payload written to Notion. |
| `SLACK_OAUTH_CLIENT_ID`, `SLACK_OAUTH_CLIENT_SECRET` | unset | Slack app credentials. |
| `SLACK_OAUTH_REDIRECT_URI` | unset | Redirect URI registered with the Slack app. |
| `SLACK_OAUTH_SCOPES` | see `.env.example` | Scopes requested at install. |
| `SLACK_SIGNING_SECRET` | unset | Verifies Slack event signatures. |
| `SLACK_BOT_TOKEN` | unset | Bot token for posting. |
| `SLACK_APP_TOKEN` | unset | App-level token for Socket Mode. |
| `SLACK_DELIVERY_MODE` | `http` | `http` for the Events API or `socket` for Socket Mode. |

## Evals

The eval harness has its own configuration surface: runner image, execution backend, evidence store, branch provider, quotas, and notifications. See [Deploying the harness](/docs/evals/deploying#environment-variables) for the full list.

## Settings that are not environment variables

- **Row limit.** `query_database` accepts a `row_limit` parameter (default `1000`, maximum `10000`). There is no global override.
- **Budget caps.** Registered per session through `/api/budget`. The `check_budget` tool reports remaining spend.
- **Audit log.** Always on. Every query is logged.
- **PII redaction in audit.** Always on. SQL string literals are replaced with `<REDACTED>`.
