# SignalPilot — Cloud Security Audit: Master Issue Index

**Audit date:** 2026-04-30
**Branch reviewed:** `autofyn/i-need-you-to-ge-30a2b9`
**Scope:** Hosted multi-tenant deployment (`signalpilot.ai`, `gateway.signalpilot.ai`). Local/Docker-compose behavior noted per finding.
**Methodology:** Static code review. All line numbers verified against source at review time.

---

## Severity legend

| Severity | Description |
|----------|-------------|
| Critical | Unauthenticated remote exploitation; full multi-tenant compromise |
| High | Authenticated exploitation or single precondition; cross-tenant access or auth bypass |
| Medium | Realistic exploitation; partial data leakage or degraded security control |
| Low | Multiple preconditions or limited impact; defense-in-depth |
| Info | No direct exploitability; design note or stub requiring hardening |

---

## Executive summary table

| # | Slug | Title | Severity | Cloud Impact | Proposal |
|---|------|--------|----------|--------------|---------|
| 7 | `mcp-auth-passthrough-when-no-keys-exist` | MCP accepts ALL unauthenticated requests when zero API keys exist | Critical | Yes | [link](mcp-auth-passthrough-when-no-keys-exist-proposal.md) |
| 1 | `clerk-jwt-audience-not-verified` | Clerk JWT `aud` claim not verified | High | Yes | [link](clerk-jwt-audience-not-verified-proposal.md) |
| 9 | `sandboxes-store-not-org-scoped` | In-memory sandbox store shared across all tenants | High | Yes | [link](sandboxes-store-not-org-scoped-proposal.md) |
| 8 | `mcp-auth-key-lookup-leaks-cross-tenant-keys` | MCP API key validated against all orgs, no tenant scope | High | Yes | [link](mcp-auth-key-lookup-leaks-cross-tenant-keys-proposal.md) |
| 10 | `scope-guard-bypass-for-jwt-requests` | All scopes granted to JWT requests regardless of endpoint dependencies | High | Yes | [link](scope-guard-bypass-for-jwt-requests-proposal.md) |
| 31 | `csp-allows-unsafe-inline-and-unsafe-eval` | CSP `script-src` includes `unsafe-inline` and `unsafe-eval` in production | High | Yes | [link](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md) |
| 2 | `clerk-jwt-no-clock-leeway-or-nbf-check` | JWT decoding does not enforce `nbf`/`iat` or set leeway | Medium | Yes | [link](clerk-jwt-no-clock-leeway-or-nbf-check-proposal.md) |
| 5 | `no-clerk-webhook-signature-verification-handler` | No Clerk webhook handler — org lifecycle events ignored | Medium | Yes | [link](no-clerk-webhook-signature-verification-handler-proposal.md) |
| 11 | `org-id-fallback-to-local-in-cloud` | `Store` defaults `org_id="local"` when org_id is unset in cloud mode | Medium | Yes | [link](org-id-fallback-to-local-in-cloud-proposal.md) |
| 12 | `audit-stats-uses-fallback-org-id` | `/api/audit/stats` uses `org_id or "local"` fallback | Medium | Yes | [link](audit-stats-uses-fallback-org-id-proposal.md) |
| 16 | `api-keys-cached-by-mcp-auth-in-process-with-no-revocation-bus` | MCP auth caches validated keys 5 min; revocations not propagated | Medium | Yes | [link](api-keys-cached-by-mcp-auth-in-process-with-no-revocation-bus-proposal.md) |
| 17 | `api-key-no-scope-for-mcp-and-no-rate-limit-per-key` | Rate limit is per-IP only; stolen key behind CDN not throttled | Medium | Yes | [link](api-key-no-scope-for-mcp-and-no-rate-limit-per-key-proposal.md) |
| 18 | `api-key-storage-allows-user-id-null-and-org-id-null` | API keys with `org_id=None`/`"local"` accepted in cloud mode | Medium | Yes | [link](api-key-storage-allows-user-id-null-and-org-id-null-proposal.md) |
| 19 | `sql-validation-bypass-via-cte-or-set-op-with-non-select-leaf` | SELECT-only validator may permit dangerous dialect functions | Medium | Yes | [link](sql-validation-bypass-via-cte-or-set-op-with-non-select-leaf-proposal.md) |
| 21 | `inject-limit-fallback-string-concat-on-parse-failure` | `inject_limit` falls back to string concatenation on parse failure | Medium | Yes | [link](inject-limit-fallback-string-concat-on-parse-failure-proposal.md) |
| 23 | `dbt-profiles-yml-written-with-plaintext-credentials` | `_create_new_project` writes plaintext credentials to `profiles.yml` | Medium | Partial | [link](dbt-profiles-yml-written-with-plaintext-credentials-proposal.md) |
| 24 | `connection-test-tcp-connect-toctou-vs-ssrf-check` | DNS rebinding window between SSRF check and `socket.connect` | Medium | Yes | [link](connection-test-tcp-connect-toctou-vs-ssrf-check-proposal.md) |
| 25 | `bigquery-and-snowflake-skip-ssrf-validation` | Cloud warehouse connectors excluded from SSRF validation | Medium | Yes | [link](bigquery-and-snowflake-skip-ssrf-validation-proposal.md) |
| 26 | `sandbox-mounts-host-data-volume-readonly-but-broad` | Sandbox container mounts entire user home directory by default | Medium | Partial | [link](sandbox-mounts-host-data-volume-readonly-but-broad-proposal.md) |
| 27 | `sandbox-execute-no-tenant-binding` | Sandbox manager `/execute` has no authentication | Medium | Partial | [link](sandbox-execute-no-tenant-binding-proposal.md) |
| 29 | `sandbox-output-html-rendered-with-dangerously-set-inner-html` | Sandbox HTML output rendered via `dangerouslySetInnerHTML` | Medium | Yes | [link](sandbox-output-html-rendered-with-dangerously-set-inner-html-proposal.md) |
| 33 | `localStorage-stores-api-key-vulnerable-to-xss` | API key persisted in `localStorage` — exfiltratable by XSS | Medium | Yes | [link](localstorage-stores-api-key-vulnerable-to-xss-proposal.md) |
| 38 | `dockerfile-gateway-runs-as-root` | `Dockerfile.gateway` runs uvicorn as UID 0 | Medium | Yes | [link](dockerfile-gateway-runs-as-root-proposal.md) |
| 40 | `sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt` | Passphrase salt derived from passphrase itself defeats salting | Medium | Yes | [link](sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt-proposal.md) |
| 42 | `cors-allow-credentials-true-with-permissive-origin-list` | `allow_credentials=True` with origins from env var including localhost | Medium | Yes | [link](cors-allow-credentials-true-with-permissive-origin-list-proposal.md) |
| 43 | `mcp-mounted-at-root-instead-of-mcp-prefix-only` | MCP ASGI app mounted at `/` instead of `/mcp` | Medium | Yes | [link](mcp-mounted-at-root-instead-of-mcp-prefix-only-proposal.md) |
| 45 | `audit-log-stores-full-sql-text-including-pii` | Audit log stores full SQL including PII literal values | Medium | Yes | [link](audit-log-stores-full-sql-text-including-pii-proposal.md) |
| 47 | `plugin-is-a-git-submodule-trusted-implicitly` | `plugin/` submodule installed without verification or pinning | Medium | Yes | [link](plugin-is-a-git-submodule-trusted-implicitly-proposal.md) |
| 50 | `auth-rate-limit-per-ip-only-allows-key-brute-force-from-many-ips` | No per-key brute-force limiter for auth failures | Medium | Yes | [link](auth-rate-limit-per-ip-only-allows-key-brute-force-from-many-ips-proposal.md) |
| 52 | `billing-page-references-stripe-but-no-webhook-route-found` | Stripe webhook handler missing from repo | Medium | Yes | [link](billing-page-references-stripe-but-no-webhook-route-found-proposal.md) |
| 56 | `cloud-mode-disables-sandbox-but-mcp-server-still-exposes-execute-code-tool` | MCP still advertises `execute_code` tool when sandbox is disabled | Medium | Yes | [link](cloud-mode-disables-sandbox-but-mcp-server-still-exposes-execute-code-tool-proposal.md) |
| 3 | `clerk-jwks-fetched-without-tls-pinning-or-failure-policy` | JWKS client has no failure-mode policy | Low | Yes | [link](clerk-jwks-fetched-without-tls-pinning-or-failure-policy-proposal.md) |
| 4 | `clerk-publishable-key-derives-issuer-via-base64` | Issuer derivation from publishable key fails at runtime not startup | Low | Yes | [link](clerk-publishable-key-derives-issuer-via-base64-proposal.md) |
| 13 | `byok-key-id-cross-tenant-confusion-on-rotate` | BYOK rotate accepts attacker-controlled `new_key_id` without org filter in query | Low | Yes | [link](byok-key-id-cross-tenant-confusion-on-rotate-proposal.md) |
| 14 | `api-key-prefix-too-short-and-collidable` | API key prefix only 7 chars; enables enumeration | Low | Yes | [link](api-key-prefix-too-short-and-collidable-proposal.md) |
| 20 | `sql-stacking-detection-regex-not-aware-of-string-literals` | Stacking detector regex not string-literal-aware | Low | Yes | [link](sql-stacking-detection-regex-not-aware-of-string-literals-proposal.md) |
| 22 | `connector-credentials-extras-include-plaintext-password-twice` | Password stored in `extras_enc` JSON in addition to connection string | Low | Yes | [link](connector-credentials-extras-include-plaintext-password-twice-proposal.md) |
| 28 | `sandbox-mount-extension-allowlist-trivially-bypassed` | `.tar.gz` files classified as `.gz` only; allowlist incomplete | Low | Partial | [link](sandbox-mount-extension-allowlist-trivially-bypassed-proposal.md) |
| 30 | `sandbox-audit-log-leaks-client-ip-but-not-org-id` | Sandbox audit logs omit `org_id`/`key_id` correlation | Low | Partial | [link](sandbox-audit-log-leaks-client-ip-but-not-org-id-proposal.md) |
| 32 | `local-key-route-exposes-key-without-auth-in-local-mode` | `/api/local-key` has no auth and no cloud-mode guard | Low | Partial | [link](local-key-route-exposes-key-without-auth-in-local-mode-proposal.md) |
| 34 | `csp-connect-src-includes-arbitrary-backend-url` | CSP `connect-src` computed from unvalidated env var | Low | Yes | [link](csp-connect-src-includes-arbitrary-backend-url-proposal.md) |
| 36 | `enterprise-route-does-not-enforce-org-admin` | `GET /api/team/enterprise` has no Clerk auth check | Low | Yes | [link](enterprise-route-does-not-enforce-org-admin-proposal.md) |
| 37 | `docker-compose-default-postgres-credentials` | `docker-compose.yml` ships weak default Postgres credentials | Low | Partial | [link](docker-compose-default-postgres-credentials-proposal.md) |
| 39 | `clerk-secret-key-required-but-not-validated-at-startup` | Missing `CLERK_PUBLISHABLE_KEY` logs error instead of failing startup | Low | Yes | [link](clerk-secret-key-required-but-not-validated-at-startup-proposal.md) |
| 41 | `legacy-sha256-key-derivation-fallback-still-present` | Legacy SHA-256 decryption fallback increases attack surface | Low | Yes | [link](legacy-sha256-key-derivation-fallback-still-present-proposal.md) |
| 44 | `request-correlation-header-not-validated` | `X-Request-ID` logged unsanitized — log injection vector | Low | Yes | [link](request-correlation-header-not-validated-proposal.md) |
| 46 | `client-ip-trust-x-forwarded-for-without-trusted-proxy-list` | X-Forwarded-For honored without trusted proxy validation | Low | Yes | [link](client-ip-trust-x-forwarded-for-without-trusted-proxy-list-proposal.md) |
| 48 | `package-lock-no-overrides-and-no-audit-step-in-ci` | No npm audit gate in CI; empty overrides | Low | Yes | [link](package-lock-no-overrides-and-no-audit-step-in-ci-proposal.md) |
| 49 | `pip-install-no-hashes-in-dockerfile` | `pip install` without `--require-hashes` in Dockerfile | Low | Yes | [link](pip-install-no-hashes-in-dockerfile-proposal.md) |
| 54 | `query-results-not-encrypted-at-rest-after-cache` | Schema/result caches may leak sensitive data via process memory | Low | Yes | [link](query-results-not-encrypted-at-rest-after-cache-proposal.md) |
| 55 | `audit-export-streams-without-row-cap` | `POST /api/audit/export` may stream unbounded rows | Low | Yes | [link](audit-export-streams-without-row-cap-proposal.md) |
| 57 | `byok-aws-config-passed-as-json-env-var` | AWS credentials in JSON env var instead of IAM role | Low | Yes | [link](byok-aws-config-passed-as-json-env-var-proposal.md) |
| 6 | `enterprise-sso-route-stub-returns-empty` | `GET /api/team/enterprise` is a no-op stub | Info | No | [link](enterprise-sso-route-stub-returns-empty-proposal.md) |
| 15 | `api-key-entropy-128-bits-fine-but-no-pepper` | API key hash uses bare SHA-256 with no HMAC/pepper | Info | Yes | [link](api-key-entropy-128-bits-fine-but-no-pepper-proposal.md) |
| 35 | `next-config-does-not-set-security-headers` | `next.config.ts` missing security hardening options | Info | Yes | [link](next-config-does-not-set-security-headers-proposal.md) |
| 51 | `request-body-2mb-limit-may-allow-large-sql-payloads` | 2 MB body limit vs. 100 KB SQL cap — intentional but undocumented | Info | Yes | [link](request-body-2mb-limit-may-allow-large-sql-payloads-proposal.md) |
| 53 | `ci-not-in-repo-cannot-audit` | No `.github/workflows/` in repo — CI/CD security cannot be assessed | Info | Yes | [link](ci-not-in-repo-cannot-audit-proposal.md) |
| 58 | `clerk-research-mentions-dev-keys-endless-fly-19` | `enterprise-connections.md` references dev hostname possibly hardcoded | Info | Partial | [link](clerk-research-mentions-dev-keys-endless-fly-19-proposal.md) |

---

## Findings by severity

### Critical

---

#### [MCP accepts ALL unauthenticated requests when zero API keys exist](mcp-auth-passthrough-when-no-keys-exist-proposal.md)
**Severity:** Critical | **Cloud impact:** Yes | **Status:** Open

`MCPAuthMiddleware` falls through to `user_id="local"` / `org_id="local"` when the global key count is zero. A fresh hosted deploy or a deploy where an admin deleted the last key exposes the full MCP tool surface to the internet without authentication.

**Affected:** `signalpilot/gateway/gateway/mcp_auth.py:196-218`

---

### High

---

#### [Clerk JWT `aud` claim not verified](clerk-jwt-audience-not-verified-proposal.md)
**Severity:** High | **Cloud impact:** Yes | **Status:** Open

`jwt.decode` passes `options={"verify_aud": False}` — any token signed by the Clerk tenant is accepted regardless of intended audience.

**Affected:** `signalpilot/gateway/gateway/auth.py:115`

---

#### [In-memory sandbox store shared across all tenants](sandboxes-store-not-org-scoped-proposal.md)
**Severity:** High | **Cloud impact:** Yes | **Status:** Open

`_active_sandboxes` is a module-global dict with no org scoping. Tenant B can list, read, and execute against Tenant A's sandbox.

**Affected:** `signalpilot/gateway/gateway/store.py:563`, `signalpilot/gateway/gateway/api/sandboxes.py:24-107`

---

#### [MCP API key validated against all orgs, no tenant scope](mcp-auth-key-lookup-leaks-cross-tenant-keys-proposal.md)
**Severity:** High | **Cloud impact:** Yes | **Status:** Open

`validate_stored_api_key` searches with no `org_id` filter. Miscreated key `org_id` leads to cross-tenant access.

**Affected:** `signalpilot/gateway/gateway/store.py:1404-1432`, `mcp_auth.py:227-241`

---

#### [All scopes granted to JWT requests regardless of endpoint dependencies](scope-guard-bypass-for-jwt-requests-proposal.md)
**Severity:** High | **Cloud impact:** Yes | **Status:** Open

`require_scopes` Case 1 grants all scopes when `auth is None`, which occurs for JWT requests. Endpoints using only `dependencies=[RequireScope(...)]` without a `UserID` dependency skip JWT verification entirely.

**Affected:** `signalpilot/gateway/gateway/scope_guard.py:34-38`

---

#### [CSP `script-src` includes `unsafe-inline` and `unsafe-eval` in production](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md)
**Severity:** High | **Cloud impact:** Yes | **Status:** Open

Both directives are hardcoded in `middleware.ts` for all deployments, defeating CSP's XSS protection when tenant-controlled content is displayed.

**Affected:** `signalpilot/web/middleware.ts:29`

---

### Medium

*(19 findings — see executive summary table for full list)*

---

### Low

*(18 findings — see executive summary table for full list)*

---

### Info

*(6 findings — see executive summary table for full list)*

---

## Out-of-scope notes

- Binary review of the `runsc` (gVisor) runtime was not performed.
- Third-party JavaScript supply chain was not audited beyond `package-lock.json` lockfile inspection.
- SOC 2 controls, organizational policies, and pen-test of the live cloud environment were not assessed.
- Stripe/billing webhook implementation is flagged as finding #52 but cannot be fully assessed from this repo alone.
- AWS/GCP/Azure account-level IAM configuration is out of scope.
- Infra-as-code (Terraform/Pulumi) is not present in the repo.

---

## Methodology appendix

**Files reviewed:**
- `signalpilot/gateway/gateway/auth.py`, `mcp_auth.py`, `middleware.py`, `scope_guard.py`, `store.py`, `main.py`, `network_validation.py`, `deployment.py`
- `signalpilot/gateway/gateway/api/{keys,connections,query,sandboxes,files,byok,settings,security,audit}.py`
- `signalpilot/gateway/gateway/engine/__init__.py`
- `signalpilot/web/middleware.ts`, `next.config.ts`, `app/layout.tsx`, `app/api/local-key/route.ts`, `app/api/team/enterprise/route.ts`, `lib/api.ts`, `lib/backend-client.ts`, `lib/auth-context.tsx`
- `Dockerfile.gateway`, `Dockerfile.sandbox`, `Dockerfile.web`, `docker-compose.yml`
- `sp-sandbox/sandbox_manager.py`, `audit.py`, `sandbox_exec.sh`
- `signalpilot/web/app/sandboxes/[id]/page.tsx`
- `signalpilot/web/clerk-research.md`, `enterprise-connections.md`

**NOT reviewed:**
- Stripe billing integration (not found in repo)
- CI/CD pipelines (no `.github/workflows/` found)
- AWS/GCP/Azure account or IAM configuration
- Network-level firewall rules and ingress controller configuration
- gVisor runtime binary
