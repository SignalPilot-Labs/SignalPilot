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

### COMPLETED

- [x] **Frontend Accessibility** — SecurityBanner collapsible has `aria-expanded`/`aria-controls`/`role="region"`, Tooltip has keyboard support (`onFocus`/`onBlur`), `role="tooltip"`, `aria-describedby` with `useId()`

## Round 4: Frontend Accessibility, XSS Prevention, Security Headers

### COMPLETED

- [x] **Frontend Accessibility** — SecurityBanner aria attributes, Tooltip keyboard + ARIA support
- [x] **Sandbox XSS Prevention** — Pure allowlist HTML sanitizer for `dangerouslySetInnerHTML` in sandbox output; strips all non-table elements and non-structural attributes; no `style` attribute allowed (CSS injection vector)
- [x] **Gateway Security Headers** — `Permissions-Policy` header added; `Strict-Transport-Security` added conditionally (HTTPS only, no `preload`); 3 new tests verify behavior

## Round 5: CORS Hardening, MySQL Quoting, Test Cleanup

### COMPLETED

- [x] **Broken Test Cleanup** — Fixed imports in `test_compact_schema.py` (→ `gateway.schema_utils`) and `test_fuzzy_search.py` (→ `gateway.api.schema`); deleted `test_audit_rotation.py` (target function removed). All 34 tests pass.
- [x] **CORS Origin Validation** — `SP_ALLOWED_ORIGINS` env var now validated: wildcard `*` rejected (credential-stealing misconfiguration with `allow_credentials=True`), non-http/https origins rejected. Warnings logged for skipped entries. 7 new tests verify behavior.
- [x] **MySQL Column Identifier Quoting** — Backtick-escape column names in `get_sample_values` fallback SQL path to prevent theoretical SQL injection via crafted column names. Dict key access correctly uses unescaped original name.

## Round 6: Docker Sandbox Hardening & Auth Rate Limiting

### COMPLETED

- [x] **Docker Sandbox Container Hardening** — read-only root filesystem, tmpfs /tmp (100MB, noexec), no-new-privileges, mem_limit 512m, cpus 2, pids_limit 256. Removed exposed port 8180 (sandbox only reachable via Docker internal networking).
- [x] **Sandbox Privilege Drop** — New `sandbox_exec.sh` wrapper script drops to nobody (UID 65534) via `setpriv` before exec'ing user code. CPU and file-size ulimits enforced. Input validation on timeout parameter prevents injection.
- [x] **Sandbox Path Traversal Fix** — `browse_files_handler` and `execute_handler` both use `Path.is_relative_to()` to confine access to `/host-data`. Prevents directory traversal to `/etc`, `/proc`, or container internals. Applied to file mount validation as well.
- [x] **Auth Endpoint Rate Limiting** — Three-tier rate limiting: auth (10rpm for `/api/keys` POST) > expensive (30rpm) > general (120rpm). Auth 429 returns early without incrementing general bucket. 3 new tests verify behavior including bucket isolation.
