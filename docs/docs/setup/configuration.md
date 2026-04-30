---
sidebar_position: 3
---

# Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and set your values before starting the stack.

## Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_DATA_DIR` | `~/.signalpilot` | Path to the directory where the gateway stores its SQLite database, encryption salt, annotations, and local state. Override per-deployment (e.g. `/var/lib/signalpilot`). |

## Encryption

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_ENCRYPTION_KEY` | — | Required. Primary key used for AES-GCM encryption of credentials at rest. |
| `SP_ENCRYPTION_SALT` | — | Required. Salt used in key derivation. Must be set alongside `SP_ENCRYPTION_KEY`. |
| `SP_ALLOW_LEGACY_CRYPTO` | `false` | Set to `true` to allow SHA-256 credential hashing during migration windows. AES-GCM is the canonical path. |
| `SP_BYOK_PROVIDER` | — | BYOK encryption provider name (e.g. `aws_kms`). Pro/Team/Enterprise plans only. |
| `SP_BYOK_PROVIDER_CONFIG` | — | JSON-encoded configuration for the BYOK provider. |

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

## Governance

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_MAX_EXPORT_ROWS` | `50000` | Maximum rows allowed in a single audit export. |
| `SP_ANNOTATIONS_TTL` | `60.0` | Cache TTL in seconds for schema annotation files. |
| `SP_ADMIN_USER_IDS` | `local` | Comma-separated user IDs with admin access. The value `local` is the single-user local-deployment sentinel. |

## SSRF protection

| Variable | Default | Description |
|----------|---------|-------------|
| `SP_ALLOW_PRIVATE_CONNECTIONS` | — | Set to `true` to allow TCP connections to RFC1918 private ranges (loopback and link-local are always blocked). Intended for self-hosted deployments where the warehouse is on a private network. Unset by default in cloud mode. |

---

**Knobs that are not env-driven:**

- **LIMIT injection default** — `query_database` accepts a `row_limit` parameter (default `1000`, max `10000`). There is no global env override; callers control the per-call limit.
- **Budget caps** — set per session via the `start_session`/`check_budget` MCP tools. There is no global default budget env var.
- **Audit log** — always enabled; every query is logged. There is no env toggle.
- **PII redaction in audit** — always active; SQL string literals are replaced with `<REDACTED>` in audit records.
