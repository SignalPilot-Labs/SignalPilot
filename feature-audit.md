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

### NOT YET EXPLORED

- [ ] **CSRF Protection** — No CSRF token validation on state-changing POST endpoints
- [ ] **Metrics/Health Exposure** — `/api/metrics` and `/health` in PUBLIC_PATHS may leak internal info
- [ ] **DuckDB/SQLite Path Traversal** — User can set `database` to arbitrary filesystem path in local mode
- [ ] **Request Body Size Limit** — No middleware-level body size limit (only SQL field max_length)
- [ ] **dbt profiles.yml Plaintext** — `profiles.yml` generation writes credentials to disk unencrypted
- [ ] **Docker Compose Hardcoded Passwords** — `POSTGRES_PASSWORD: testpass` should be documented as dev-only
- [ ] **Frontend Accessibility** — SecurityBanner collapsible needs `aria-expanded`/`aria-controls`, Tooltip keyboard support
- [ ] **Key Rotation Support** — `key_version` column for multi-key decryption support
- [ ] **Full E2E Testing** — Docker-based integration tests with real DB connections
