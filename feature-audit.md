# SignalPilot Security Audit — Feature Tracker

## Round 1: Credential Encryption Hardening & Critical Security Fixes

### COMPLETED

- [x] **DB Credential Encryption at Rest** — PBKDF2-HMAC-SHA256 key derivation (600k iterations), persistent salt, key file permissions 0600, migration path from legacy SHA-256 derivation
- [x] **MCP Auth Bypass Fix** — DB errors now fail closed (401) instead of passing through unauthenticated
- [x] **Rate Limiter Hardening** — X-Forwarded-For uses rightmost (trusted proxy) IP instead of leftmost (attacker-controlled)
- [x] **Sandbox Error Sanitization** — `execute_code_with_mounts()` no longer leaks raw exception details
- [x] **Export Endpoint Hardening** — Changed to POST-only with confirmation body, audit logging added
- [x] **Connection Filter Access Control** — `_conn_filter` fails closed when user_id is None, requires explicit `allow_unscoped=True`
- [x] **Security Status Endpoint** — Admin-only `/api/security/status` for encryption health monitoring
- [x] **Frontend Security Messaging** — SecurityBanner on connections page + encrypted badges on connection cards
- [x] **Import Endpoint Error Sanitization** — Raw exception strings replaced with generic messages
- [x] **Warmup Endpoint Error Sanitization** — Uses `sanitize_db_error()` instead of raw `str(e)`
- [x] **Middleware Logging** — API key DB validation failures now logged (was silent `except: pass`)

## Round 2: Security Hardening — MEDIUM Findings

### COMPLETED

- [x] **CSRF Protection** — Mitigated by existing architecture: CORS allowlist restricts cross-origin requests; all state-changing endpoints require `X-API-Key` or `Authorization: Bearer` headers (custom headers blocked cross-origin without CORS preflight); Clerk JWT in `__session` cookie is cryptographically verified — CSRF cannot forge a valid JWT. No code change needed.
- [x] **DuckDB/SQLite Path Traversal** — `_validate_local_db_path()` added to store.py; restricts paths to `DATA_DIR` only (no `Path.home()`); validated at the `raw_cred` chokepoint in `create_connection()` (catches `connection_string` direct-bypass) AND at input validation layer in `api/connections.py` (defense in depth). `:memory:` and `md:` prefixes remain unaffected.
- [x] **Request Body Size Limit** — 2MB limit enforced by `RequestBodySizeLimitMiddleware` (raw ASGI, not `BaseHTTPMiddleware`) — rejects oversized bodies before auth processing; registered second-outermost so CORS headers still appear on 413 responses.
- [x] **dbt profiles.yml Plaintext** — `profiles.yml` written with `chmod 0o600`, project directory set to `chmod 0o700` in `_create_new_project()`.
- [x] **Docker Compose Hardcoded Passwords** — `docker-compose.yml` postgres service documented as dev-only with inline warning comment.

### COMPLETED

- [x] **Metrics/Health Exposure** — `/api/metrics` removed from `PUBLIC_PATHS` (requires auth); payload stripped of `sandbox_manager` URL, `query_cache`, and `schema_cache` internals; `/health` verified safe (only `status` + `version`). 19 tests verify auth enforcement and payload sanitization.
- [x] **Key Rotation Support** — `key_version` column added to `GatewayCredential` with `server_default="1"`; idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` migration in `engine.py`; `CURRENT_KEY_VERSION` constant in `store.py`; lazy re-encryption on version mismatch re-encrypts BOTH `connection_string_enc` and `extras_enc` atomically; `get_credentials_needing_rotation()` global count; security status endpoint reports `current_key_version` and `total_credentials_pending_rotation`.
- [x] **E2E Test Fixes** — Fixed `Base` → `GatewayBase` import bug; fixed sync→async cleanup fixture; added key_version and special-character round-trip tests.

### NOT YET EXPLORED

- [ ] **Frontend Accessibility** — SecurityBanner collapsible needs `aria-expanded`/`aria-controls`, Tooltip keyboard support
