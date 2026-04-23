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

## Round 7: Sandbox Network Isolation, Audit Logging, CSP Headers

### COMPLETED

- [x] **Sandbox Network Isolation** — Docker Compose `frontend`/`backend` named networks added. `backend` network has `internal: true` to block outbound internet egress. `sandbox` and `postgres` restricted to `backend` only; `web` restricted to `frontend` only; `gateway` bridges both. Sandbox can still reach `gateway:3300` and `postgres:5432` (intentional — core product functionality). No service names, env vars, or ports changed.
- [x] **Sandbox Audit Logging** — New `sp-sandbox/audit.py` module emits structured JSON log lines to `sandbox_audit` logger. Logs `event`, `timestamp` (UTC ISO-8601), `session_token` (first 8 chars only), `vm_id`, `code_length`, `code_hash` (SHA-256 — never the code itself), `timeout`, `mount_count`, `success`, `error`, `execution_ms`, `client_ip`. `sandbox_manager.py` calls `audit.log_execution()` after every execution and on validation failures (code too long, rate limited, mount path denied). Audit errors are swallowed with a WARNING log — never affect execution response.
- [x] **Content-Security-Policy Header** — `SecurityHeadersMiddleware` in gateway now sets `Content-Security-Policy` on all responses. Default policy: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`. Configurable via `SP_GATEWAY_CSP_POLICY` env var (full override, no merging). `script-src` has no `'unsafe-inline'` — intentionally breaks `/docs` Swagger UI in production. 4 new gateway tests + 5 audit unit tests added.

## Round 8: API Key Scope Enforcement, Expiry, JWT Error Sanitization

### COMPLETED

- [x] **API Key Scope Enforcement** — `scope_guard.py` module with `require_scopes()` and `RequireScope()` factory. Three auth cases: JWT/Clerk (no auth dict → grant all), local_key (grant all), api_key (check scopes explicitly). Unknown auth methods fail closed (403). Scopes propagated via `request.state.auth["scopes"]` in middleware.
- [x] **Scope Allowlist Validation** — `VALID_API_KEY_SCOPES` frozenset (`read`, `query`, `execute`, `write`, `admin`). Pydantic `field_validator` on `ApiKeyCreate.scopes` rejects unknown scopes at API boundary. Flat model — no hierarchy.
- [x] **API Key Expiry** — Optional `expires_at` column (TEXT, ISO-8601 UTC) on `GatewayApiKey`. Idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` migration. Validated at input (must be timezone-aware ISO-8601). Expiry check in `validate_stored_api_key()` with try/except for corrupt data (fail closed). Null = never expires (backward-compatible).
- [x] **JWT Error Detail Leak Fix** — `auth.py` no longer returns `f"Invalid token: {e}"` to clients. Generic `"Invalid authentication token"` response; actual error logged at WARNING level server-side.
- [x] **API Key user_id Propagation Fix** — `ApiKeyRecord` now includes `user_id` field populated from DB row. Pre-existing bug where all API keys resolved to `user_id="local"` is fixed.
- [x] **Key Management Scope Protection** — All key management endpoints (`GET /keys`, `POST /keys`, `DELETE /keys/{key_id}`) require `RequireScope("admin")`. Prevents read-only keys from listing, creating, or deleting API keys.
- [x] **27 new tests** covering scope guard logic, allowlist validation, key expiry, user_id propagation, JWT error redaction, and expires_at validation.

## Round 9: Full Scope Enforcement, SSRF Prevention

### COMPLETED

- [x] **Full Endpoint Scope Enforcement** — `RequireScope()` guards added to 29 endpoints across 8 router files. Write endpoints (connections CRUD, import/export, clone, projects CRUD, cache invalidation, budget, schema mutations) require `write`. Sandbox endpoints require `execute`. Query endpoints require `query`. Settings and key management require `admin`. Read-adjacent endpoints that make outbound connections (test, diagnose) require `read`.
- [x] **SSRF Host Validation** — New `network_validation.py` module. Resolves ALL DNS records (prevents rebinding), checks every resolved IP against blocked ranges. Blocks loopback (127.0.0.0/8, ::1), link-local (169.254.0.0/16 including AWS metadata, fe80::/10), unspecified (0.0.0.0, ::). IPv4-mapped IPv6 bypass prevented (::ffff:169.254.169.254). DNS failure = fail closed. Thread-safe via threading.Lock on socket.setdefaulttimeout.
- [x] **TCP-only SSRF Validation** — Only applied to TCP-based db_types (postgres, mysql, mssql, redshift, clickhouse, trino). Cloud (snowflake, bigquery, databricks) and embedded (duckdb, sqlite) types skip validation.
- [x] **SP_ALLOW_PRIVATE_CONNECTIONS** — Env var allows RFC1918 ranges for legitimate internal database deployments. Loopback and link-local (including metadata endpoints) remain blocked even when enabled. Warning logged at startup.
- [x] **Import Endpoint SSRF Fix** — `import_connections` now validates connection params before storing, preventing SSRF bypass where imported connections targeting internal IPs could be exploited via test/diagnose endpoints.
- [x] **Fail-closed on missing host** — TCP db_types with no extractable host raise ValueError instead of silently passing SSRF validation.
- [x] **RequireScope lambda→def fix** — Fixed FastAPI DI issue where lambda-based RequireScope caused 422 errors (Request treated as query parameter).
- [x] **88 new tests** (43 SSRF validation + 45 scope enforcement endpoints) — all passing. 255 total tests green.

## Round 10: CGNAT SSRF Bypass Fix, Session Token Hardening

### COMPLETED

- [x] **CGNAT SSRF Bypass Fix** — `ALWAYS_BLOCKED_NETWORKS` tuple added to `network_validation.py` containing `100.64.0.0/10` (CGNAT / Shared Address Space, RFC 6598) and `192.88.99.0/24` (deprecated 6to4 relay anycast, RFC 7526). Python 3.12's `ipaddress.is_private` returns `False` for CGNAT, allowing attackers to target cloud-provider internal ranges. Fixed by explicit network-range denylist checked before `is_private`. CGNAT is always blocked regardless of `SP_ALLOW_PRIVATE_CONNECTIONS`.
- [x] **IPv4-Mapped IPv6 CGNAT Bypass Prevented** — `_is_blocked_address()` is the single enforcement point called by both the direct IPv4/IPv6 path and the IPv4-mapped IPv6 extraction path in `_check_ip_address()`. No changes to `_check_ip_address()` were needed; the CGNAT check applies to both paths automatically.
- [x] **Session Token Leak Fix** — `list_vms_handler()` in `sandbox_manager.py` now returns `token[:8] + "..."` instead of the full token in `/vms` responses. Prevents session token enumeration by anyone reaching the sandbox manager.
- [x] **Session Token Length Validation** — `execute_handler()` rejects `session_token` longer than 128 chars with `400 {"error": "Invalid session token"}` before any audit logging or dict storage. Prevents memory exhaustion from oversized tokens stored as dict keys.
- [x] **16 new tests** — 10 CGNAT/6to4 tests in `test_ssrf_validation.py` (including IPv4-mapped bypass, edge cases at range boundaries, `SP_ALLOW_PRIVATE_CONNECTIONS` always-blocked behavior) + 6 sandbox session tests in `sp-sandbox/test/test_sandbox_session.py` (token truncation format, empty sessions, oversized rejection, audit-logging not called before rejection). All 53 SSRF tests + 6 sandbox tests pass.

## Round 11: Settings Secret Redaction, Sandbox Scope Guards, Log Sanitization

### COMPLETED

- [x] **GET /settings Secret Redaction + Scope Guard** — `GET /api/settings` now requires `admin` scope (previously unguarded, any authenticated user could read). Response masks `api_key` and `sandbox_api_key` to `"****"` (if set) or `null` (if unset). No raw key material returned in API responses.
- [x] **PUT /settings Secret Redaction + Mask Round-Trip Protection** — `PUT /api/settings` response also masks secrets. Critical: if client sends `"****"` back (GET→modify→PUT cycle), the endpoint preserves the existing stored key instead of overwriting with the mask string.
- [x] **Local API Key Log Sanitization** — `store.py` no longer logs `key[:12]` at generation time (exposed first 3 chars of secret portion). Now logs only the key file path.
- [x] **Sandbox GET Scope Guards** — `GET /api/sandboxes` and `GET /api/sandboxes/{sandbox_id}` now require `read` scope. Previously any authenticated user could list/inspect all sandboxes regardless of API key scopes.
- [x] **Pre-existing test_get_settings Fix** — Updated `test_api.py::TestSettingsEndpoint` to expect 401 for unauthenticated requests (was previously broken since R8).
- [x] **29 new tests** — 20 settings security tests (scope enforcement, secret masking, null handling, PUT redaction, mask round-trip preservation) + 9 scope enforcement tests (sandbox read scope, settings admin scope). All pass.

## Round 12: Comprehensive GET Endpoint Scope Sweep

### COMPLETED

- [x] **Audit Endpoints Admin Guard** — `GET /api/audit` and `GET /api/audit/export` now require `admin` scope. Compliance-sensitive data (SQL queries, connection names, agent IDs, timing) was previously readable by any authenticated API key.
- [x] **File Browser Read Guard** — `GET /api/files/browse` now requires `read` scope. The endpoint proxies to the sandbox manager and exposes host filesystem contents.
- [x] **Network Info Admin Guard** — `GET /api/network/info` now requires `admin` scope. Returns hostname, all local IPs, and public IP — infrastructure reconnaissance data useful for lateral movement.
- [x] **Connection List/Detail Read Guards** — `GET /connections`, `GET /connections/{name}`, `GET /connections/health`, `GET /connections/stats`, `GET /connections/{name}/health`, `GET /connections/{name}/health/history`, `GET /connectors/capabilities`, `GET /connections/{name}/capabilities` all now require `read` scope. Previously any scope (including `execute`-only or `query`-only) could enumerate all connections.
- [x] **Projects Read Guards** — `GET /projects` and `GET /projects/{name}` now require `read` scope.
- [x] **Schema Read Guards (21 endpoints)** — All schema GET endpoints now require `read` scope: `/schema`, `/schema/grouped`, `/schema/samples`, `/schema/enriched`, `/schema/compact`, `/schema/ddl`, `/schema/agent-context`, `/schema/link`, `/schema/explore-table`, `/schema/overview`, `/schema/diff`, `/schema/refresh-status`, `/schema/diff-history`, `/schema/changes`, `/schema/filter`, `/schema/relationships`, `/schema/join-paths`, `/schema/sample-values`, `/schema/search`, `/schema/endorsements`, `/semantic-model`.
- [x] **Budget Read Guards** — `GET /budget`, `GET /budget/{session_id}`, `GET /connections/{name}/annotations` now require `read` scope.
- [x] **Cache/Pool Stats Read Guards** — `GET /cache/stats`, `GET /pool/stats`, `GET /schema-cache/stats` now require `read` scope.
- [x] **Metrics Read Guard** — `GET /metrics` (SSE stream) now requires `read` scope. Previously authenticated but unscoped.
- [x] **Duplicate Capabilities Routes Guarded** — Both copies of `GET /connectors/capabilities` and `GET /connections/{name}/capabilities` (in both `connections.py` and `metrics.py`) are guarded with `read` scope.
- [x] **URL Utility POSTs Read-Scoped** — `POST /connections/parse-url`, `POST /connections/validate-url`, `POST /connections/build-url` now require `read` scope. Previously no scope required.
- [x] **31 new tests** — TestAuditAdminScope (5), TestFilesBrowseReadScope (2), TestNetworkInfoAdminScope (3), TestConnectionsGetReadScope (11), TestProjectsGetReadScope (5), TestSchemaGetReadScope (7), TestBudgetGetReadScope (4), TestCacheStatsReadScope (6), TestMetricsReadScope (2), TestUrlUtilityReadScope (6). 102 total scope enforcement tests pass.
- [x] **Updated TestParseUrlEndpointsUnauthenticated** — Renamed to TestUrlUtilityReadScope and updated to expect 403 without `read` scope (3 tests updated to reflect new scope requirement).

## Round 13: Request Correlation IDs

### COMPLETED

- [x] **RequestCorrelationMiddleware** — Raw ASGI middleware (matches `RequestBodySizeLimitMiddleware` pattern). Generates a UUID4 correlation ID for every HTTP request. Accepts client-provided `X-Request-ID` only if it passes strict format validation (`re.fullmatch(r'[a-zA-Z0-9\-]{1,64}', value)`); rejects header injection attempts. Stores ID on `scope["state"]["request_id"]` for downstream access. Echoes ID in `X-Request-ID` response header via wrapped `send` callable.
- [x] **`get_request_id(request)` helper** — Extracts `request.state.request_id` for use in router handlers and logging.
- [x] **Middleware Stack Registration** — `RequestCorrelationMiddleware` registered as innermost middleware (added first, before `SecurityHeadersMiddleware`). Stack outermost→innermost: CORS → RequestBodySizeLimit → SecurityHeaders → RateLimit → APIKeyAuth → RequestCorrelation.
- [x] **SandboxClient Header Propagation** — `execute()` and `execute_code_with_mounts()` accept optional `request_id: str | None` parameter. When provided, includes `X-Request-ID` in outbound HTTP requests to sandbox manager for end-to-end tracing.
- [x] **Auth Middleware Correlation Logging** — `APIKeyAuthMiddleware` logs `INFO "request METHOD PATH user=USER request_id=ID"` on successful authentication (both local_key and stored api_key paths), using `getattr(request.state, "request_id", "unknown")` fallback.
- [x] **8 new tests** in `test_correlation.py` — UUID4 generation, client ID echo, injection replacement, oversized replacement, empty generation, consistency, alphanumeric acceptance, special char rejection. All pass.

## Round 14: CORS X-Request-ID Exposure & Comment Fix

### COMPLETED

- [x] **CORS expose_headers** — Added `expose_headers=["X-Request-ID"]` to CORSMiddleware config so browser JavaScript can read the correlation ID from cross-origin responses.
- [x] **CORS allow_headers** — Added `"X-Request-ID"` to `allow_headers` list so browser clients can send client-generated correlation IDs on cross-origin requests.
- [x] **Middleware ordering comment fix** — Updated stale comment block in `main.py` to accurately describe the actual middleware execution order: CORS → BodySizeLimit → SecurityHeaders → RateLimit → Correlation → Auth.
- [x] **2 new tests** in `test_cors.py` — CORS expose_headers verification (GET with Origin), CORS allow_headers verification (OPTIONS preflight). Both pass.

## Round 15: SQL Injection Fixes

### COMPLETED

- [x] **CRITICAL: `filter_pattern` SQL injection in `explore_column_values`** — User-supplied LIKE pattern now has single quotes escaped via `filter_pattern.replace("'", "''")` before interpolation into SQL. Length capped at 200 chars with a 422 response for over-length values. Prior code used raw string interpolation with zero escaping.
- [x] **HIGH: Unquoted `table` in `explore_column_values`** — `table` query parameter now routed through `_quote_table_name(table, quote)` before use in both `explore_sql` (SELECT FROM) and `null_sql` (COUNT FROM). Previously `FROM {table}` used raw user input.
- [x] **HIGH: Unescaped `column` in `explore_column_values`** — Column quoting replaced manual `f"{quote}{column}{close_quote}"` with `_quote_identifier(column, quote)`, which correctly escapes embedded quote characters for all dialects including MSSQL bracket quoting.
- [x] **HIGH: Unquoted `table_key` in `explore_columns_deep`** — `stat_sql` now uses `_quote_table_name(table_key, q)` instead of bare `{table_key}`. The `q` variable is already computed in the surrounding loop for column quoting.
- [x] **`_quote_identifier` / `_quote_table_name` helpers added to `schema.py`** — Module-level helpers mirror `BaseConnector._quote_identifier` (base.py:63-68). Marked with `# Mirrors BaseConnector._quote_identifier` comment. Duplicated (not imported) because the API layer has no connector instance at SQL construction time.
- [x] **MEDIUM: `_quote_table` in `mcp_server.py` did not escape embedded `"`** — Fixed to use `p.replace('"', '""')` matching the pattern in `base.py:68`. All callers automatically benefit.
- [x] **MEDIUM: Manual table quoting at mcp_server.py line 658** — Replaced `f'"{table_schema}"."{table_name}"'` with `_quote_table(full_name)` so embedded quote escaping applies and the helper is used consistently.
- [x] **MEDIUM: Unescaped `col_name` in date range query (mcp_server.py line 655-656)** — `col_name` now escaped with `.replace('"', '""')` before wrapping in double quotes for both identifier use and alias use.
- [x] **MEDIUM: Unescaped `key` in grain analysis (mcp_server.py line 2642)** — `key` now escaped with `key.replace('"', '""')` before wrapping in double quotes in the `COUNT(DISTINCT ...)` query.
- [x] **MEDIUM: Backtick injection in `clickhouse.py` fallback path** — Replaced `` f'`{col}`' `` with `self._quote_identifier(col)`. `ClickHouseConnector` already overrides `_identifier_quote` to return `` ` ``, so the method correctly escapes embedded backticks.
- [x] **MEDIUM: Single-quote injection in `mssql.py` string literal** — Column name in `SELECT '{col}' AS _col` now escaped with `safe_name = col.replace("'", "''")`. Matches the pattern in `base.py:267`.
- [x] **26 new tests** in `test_sql_injection.py` — Unit tests for `_quote_identifier`, `_quote_table_name`, `_quote_table`, `ClickHouseConnector._quote_identifier`, MSSQL literal escaping; integration tests for `explore_column_values` scope enforcement and filter_pattern length cap; negative injection tests verifying SQL logic cannot escape the literal context.

## Round 16: Timing Attack Audit & Dependency Vulnerability Scanning

### COMPLETED

- [x] **Constant-time token comparison audit: PASS** — Both secret comparison sites already use `hmac.compare_digest()`: `middleware.py:166` (local dev key) and `store.py:1111` (stored API key hashes). Sandbox manager uses dict hash-table lookups (not string comparisons). MCP auth delegates to `validate_api_key()` which calls `store.validate_stored_api_key()`. No timing attack vectors found.
- [x] **HIGH: Next.js DoS (GHSA-q4gf-8mx6-v5v3, CVSS 7.5)** — `next` bumped from `16.2.1` to `16.2.4` in `signalpilot/web/package.json`. Denial of Service via Server Components (CWE-770). `eslint-config-next` also bumped to `16.2.4` to maintain version sync. `npm audit` reports 0 vulnerabilities.
- [x] **Python runtime dependencies: CLEAN** — `pip-audit` found no vulnerabilities in fastapi, uvicorn, httpx, cryptography, PyJWT, sqlalchemy, or any other runtime dependency.
- [x] **pip 25.0.1 CVEs noted** — CVE-2025-8869 and CVE-2026-1703 affect pip itself (build tool only, not production runtime). Not actionable in application code.

## Round 17: Technology Fingerprinting Suppression & Frontend HSTS

### COMPLETED

- [x] **Uvicorn Server header suppressed (`cli.py`)** — Added `server_header=False` to `uvicorn.run()` in `gateway/cli.py`. Prevents uvicorn from sending `Server: uvicorn` on every HTTP response, removing a passive reconnaissance vector revealing the ASGI server identity.
- [x] **Uvicorn Server header suppressed (`mcp_server.py`)** — Added `server_header=False` to `uvicorn.run()` in `gateway/mcp_server.py` (streamable-HTTP transport path). Same fix applied to the MCP server entry point.
- [x] **Next.js X-Powered-By header suppressed** — Added `poweredByHeader: false` to `next.config.ts`. Prevents Next.js from sending `X-Powered-By: Next.js` on every response.
- [x] **Frontend HSTS header added** — `applySecurityHeaders()` in `middleware.ts` now sets `Strict-Transport-Security: max-age=63072000; includeSubDomains` when `x-forwarded-proto === "https"`. Matches the backend `SecurityHeadersMiddleware` HSTS policy (same `max-age`, no `preload`).

## Round 18: REST API Error Response Sanitization

### COMPLETED

- [x] **Global exception handler** — `@app.exception_handler(Exception)` registered in `main.py`. Re-raises `HTTPException` and `StarletteHTTPException` so intentional 4xx/5xx errors pass through unchanged. All other unhandled exceptions return `{"detail": "Internal server error"}` with status 500; actual exception is logged server-side with `logger.exception()`.
- [x] **connections.py: 10 sites sanitized** — Line 379 (duplicate connection 409): generic "Connection already exists or invalid parameters". Lines 843/848 (test_credentials invalid params/build error): generic static messages. Line 909 (network unreachable): exception message capped at 100 chars. Line 920 (catch-all network): generic "Could not verify network connectivity". Line 1087 (parse-url): generic "Invalid URL format". Line 1182 (build-url): generic "Failed to build URL". Lines 1456/1477/1509 (diagnose_connection DNS/TCP/TLS errors): exception messages capped at 100 chars.
- [x] **projects.py: line 28** — `detail=str(e)` replaced with `"Project already exists"`.
- [x] **sandbox_client.py: line 88** — `str(e)` replaced with `"Sandbox communication error"`; actual exception logged at ERROR level.
- [x] **engine/__init__.py: line 95** — SQL parse error now `f"SQL parse error: {str(e)[:100]}"` — preserves user-diagnostic value (reflects user-supplied SQL) while capping length.
- [x] **13 new tests** in `test_error_sanitization.py` — Global handler 500 behavior (5 tests), HTTPException pass-through (not swallowed as 500), SQL parse error cap (3 tests), connections/projects endpoint message sanitization (5 tests, skip when auth middleware blocks).

## Round 19: MCP Server Error Sanitization

### COMPLETED

- [x] **`mcp_errors.py` helper module** — `sanitize_mcp_error(error, *, cap=200)` applies sensitive pattern redaction, path stripping (`/home/`, `/var/`, `/opt/`, `/tmp/`, `/etc/`, `C:\`), Python traceback frame stripping, and length capping. `sanitize_proxy_response(status_code, body)` wraps REST API proxy responses with sanitization. `_SENSITIVE_PATTERNS` duplicated from `api/deps.py` (sync test added).
- [x] **37 sites sanitized in `mcp_server.py`** — Category A (infra): sandbox URL removed from 3 error sites (lines 172, 201, 401, 404). Category B (DB errors): 19 sites wrapped with `sanitize_mcp_error(cap=300)` preserving diagnostic text for Spider2.0 agent self-correction. Category C (file I/O): 6 sites use `.name` instead of full path + sanitize. Category D (proxy responses): 14 sites including all 8 untruncated `resp.text` sites and 3 additional CTE/validate_query sites from spec review. Category E (validation): 1 defense-in-depth site.
- [x] **Reviewer critical issues addressed** — Item 1: 8 untruncated `resp.text` sites wrapped with `sanitize_proxy_response`. Item 2: Lines 2318/2353 (CTE debugger) and line 1844 (validate_query) sanitized. Item 3: `source_error` (line 2728) sanitized before return at line 2740. Item 5: Line 201 sandbox error output wrapped with `sanitize_mcp_error`.
- [x] **Spider2.0 self-correction preserved** — DB query errors use `cap=300` to retain diagnostic text; `query_error_hint()` pattern matching still uses raw `err_str` (server-side only); sanitized copy returned to client.
- [x] **28 new tests** in `test_mcp_error_sanitization.py` — Sensitive pattern redaction (6), path stripping (3), traceback stripping (1), length capping (3), clean passthrough (2), empty string (1), proxy response formatting (5), drift guard for `_SENSITIVE_PATTERNS` sync (1), integration tests: sandbox URL not leaked (2), query error diagnostic preserved (3), schema fetch redacted (2).

## Round 20: Race Conditions & TOCTOU Fixes

### COMPLETED

- [x] **Encryption Salt TOCTOU Fix** — `_load_or_create_salt()` replaced `if exists / write_bytes` with `_atomic_create_file()` using `os.O_CREAT | os.O_EXCL | os.O_WRONLY`. Prevents catastrophic data loss where concurrent process starts could overwrite the salt, rendering credentials encrypted with the losing salt undecryptable.
- [x] **Encryption Key TOCTOU Fix** — `_get_encryption_key()` auto-key path uses same atomic file creation pattern. `.strip()` preserved on read path.
- [x] **Local API Key TOCTOU Fix** — `get_local_api_key()` uses `_atomic_create_file()` with bytes→str decode. Empty-content guard preserved: if file exists but is empty, unlinks and regenerates.
- [x] **Connection CRUD Race Fix** — `create_connection()` wraps `session.commit()` in `try/except IntegrityError` with constraint-name filtering (`uq_gw_conn_user_name`, `uq_gw_cred_user_conn`). Converts to clean `ValueError` instead of unhandled 500. Non-uniqueness IntegrityErrors re-raised.
- [x] **Project CRUD Race Fix** — `create_project()` same pattern, filters on `uq_gw_proj_user_name`.
- [x] **Clone Connection 409 Fix** — `clone_connection()` catches `ValueError` from `store.create_connection()` and returns proper `HTTPException(409)` instead of 500.
- [x] **Concurrency Audit (clean areas)** — Budget ledger, schema cache, query cache (all `threading.Lock`), pool manager (`asyncio.Lock`), API key management (UUID PKs), sandbox dict (asyncio single-threaded) — all already properly protected.
- [x] **18 new tests** in `test_concurrency.py` — Atomic file creation (6), salt convergence (2), key convergence (2), local API key convergence (2), IntegrityError handling for connections (3), IntegrityError handling for projects (2), clone connection 409 (1). All pass.

## Round 21: Input Validation Sweep

### COMPLETED

- [x] **Enum Bypass Prevention** — `SSHTunnelConfig.auth_method` constrained to `Literal["password", "key", "agent"]`, `SSLConfig.mode` to `Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]`, `ProjectCreate.link_mode` to `Literal["link", "copy"]`, `ProjectUpdate.status` to existing `ProjectStatus` enum. Previously accepted any string.
- [x] **String Length Limits (Models)** — Added `max_length` to 14 string fields across `ProjectCreate`, `ProjectUpdate`, `SandboxCreate`, `MCPToolCall`, `GatewaySettings` models. Prevents oversized values that bypass the 2MB body limit via many small fields.
- [x] **Numeric Bounds (SandboxCreate)** — `budget_usd` bounded `ge=0.01, le=10_000.0`, `row_limit` bounded `ge=1, le=100_000`, `timeout_seconds` bounded `ge=1, le=3600`. Prevents nonsensical values.
- [x] **List Size Caps** — `tags` capped at 50 items (64 chars each), `schema_filter_include/exclude` at 100 items (256 chars each), `blocked_tables` at 500 items (256 chars each). Prevents memory exhaustion via unbounded list growth.
- [x] **Import Array DoS Prevention** — `/connections/import` capped at 500 connections per request (previously unlimited).
- [x] **URL/String Length Caps (Endpoints)** — `parse_connection_url` URL capped at 4096, `validate_connection_url` at 4096, `build_connection_url` fields capped (host 255, database 128, username 128, password 1024).
- [x] **Schema Query Param Limits** — `max_length` added to 12 query parameters across schema.py (table, column, filter, question, search, etc.).
- [x] **Endorsements/Columns List Caps** — `update_endorsements` capped at 1000 items per list (256 chars each), `correct_columns` at 100, `explore_columns_deep` at 50.
- [x] **Audit/Files Query Param Limits** — `limit` bounded `ge=1`, `offset` bounded `ge=0`, `connection_name`/`event_type` capped at 64 chars. Files `path` at 4096, `pattern` at 256.
- [x] **Cookie Security Audit: CLEAN** — Gateway never sets cookies; only reads Clerk-managed `__session` cookie (HttpOnly/Secure/SameSite set by Clerk JS SDK).
- [x] **Session Fixation Audit: CLEAN** — Gateway is stateless (JWT + API key hash per-request). No server-side sessions to fixate.
- [x] **ReDoS Audit: CLEAN** — All regex patterns use simple constructs without nested quantifiers.
- [x] **72 new tests** in `test_input_validation.py` — Enum validation (6), string length limits (8), list size limits (4), import array cap (1), untyped dict validation (3), numeric bounds (3), query param limits (API-level). All pass.
