# SignalPilot — Cloud Security Audit: Master Issue Index

**Audit date:** 2026-04-30 (round 1) / re-verified 2026-04-30 (round 2)
**Branch reviewed:** `autofyn/i-need-you-to-ge-30a2b9`
**Scope:** Hosted multi-tenant deployment (`signalpilot.ai`, `gateway.signalpilot.ai`). Local/Docker-compose behavior noted per finding.
**Methodology:** Static code review. Round 2 re-verified every round-1 finding against the source and added 10 new findings (#59-#68). See `/tmp/round-2/audit-verification.md` for the per-finding verification log.
**Total findings:** 68 (55 valid as originally written + 1 stale + 1 fixed + 10 new).

---

## Severity legend

| Severity | Description |
|----------|-------------|
| Critical | Unauthenticated remote exploitation; full multi-tenant compromise |
| High | Authenticated exploitation or single precondition; cross-tenant access or auth bypass |
| Medium | Realistic exploitation; partial data leakage or degraded security control |
| Low | Multiple preconditions or limited impact; defense-in-depth |
| Info | No direct exploitability; design note or stub requiring hardening |

Status column legend (round 2): `Open` = unverified-as-fixed, `Stale` = original cite no longer applies but residual concern remains, `Fixed` = remediation observed in source.

---

## Executive summary table

| # | Slug | Title | Severity | Cloud Impact | Status | Proposal |
|---|------|--------|----------|--------------|--------|---------|
| ~~7~~ | ~~`mcp-auth-passthrough-when-no-keys-exist`~~ | ~~MCP accepts ALL unauthenticated requests when zero API keys exist~~ | ~~Critical~~ | ~~Yes~~ | **Fixed** | [link](mcp-auth-passthrough-when-no-keys-exist-proposal.md) |
| ~~1~~ | ~~`clerk-jwt-audience-not-verified`~~ | ~~Clerk JWT `aud` claim not verified~~ | ~~High~~ | ~~Yes~~ | **Fixed** | [link](clerk-jwt-audience-not-verified-proposal.md) |
| ~~9~~ | ~~`sandboxes-store-not-org-scoped`~~ | ~~In-memory sandbox store shared across all tenants~~ | ~~High~~ | ~~Yes~~ | **Fixed** (deprioritized — feature disabled) | [link](sandboxes-store-not-org-scoped-proposal.md) |
| ~~8~~ | ~~`mcp-auth-key-lookup-leaks-cross-tenant-keys`~~ | ~~MCP API key validated against all orgs, no tenant scope~~ | ~~High~~ | ~~Yes~~ | **Fixed** | [link](mcp-auth-key-lookup-leaks-cross-tenant-keys-proposal.md) |
| ~~10~~ | ~~`scope-guard-bypass-for-jwt-requests`~~ | ~~All scopes granted to JWT requests regardless of endpoint dependencies~~ | ~~High~~ | ~~Yes~~ | **Fixed** | [link](scope-guard-bypass-for-jwt-requests-proposal.md) |
| ~~31~~ | ~~`csp-allows-unsafe-inline-and-unsafe-eval`~~ | ~~CSP `script-src` includes `unsafe-inline` and `unsafe-eval` in production~~ | ~~High~~ | ~~Yes~~ | **Fixed** (unsafe-eval removed; nonce+strict-dynamic added; unsafe-inline kept as fallback per CSP spec) | [link](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md) |
| 59 | `git-clone-arg-injection-via-project-import` | `git clone` invoked with user URL/branch and no `--` separator | High | Partial | Open (deprioritized — feature disabled) | [link](git-clone-arg-injection-via-project-import-proposal.md) |
| 2 | `clerk-jwt-no-clock-leeway-or-nbf-check` | JWT decoding does not enforce `nbf`/`iat` or set leeway | Medium | Yes | Open | [link](clerk-jwt-no-clock-leeway-or-nbf-check-proposal.md) |
| 5 | `no-clerk-webhook-signature-verification-handler` | No Clerk webhook handler — org lifecycle events ignored | Medium | Yes | Open | [link](no-clerk-webhook-signature-verification-handler-proposal.md) |
| ~~11~~ | ~~`org-id-fallback-to-local-in-cloud`~~ | ~~`Store` defaults `org_id="local"` when org_id is unset in cloud mode~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** | [link](org-id-fallback-to-local-in-cloud-proposal.md) |
| 12 | `audit-stats-uses-fallback-org-id` | `/api/audit/stats` uses `org_id or "local"` fallback | Medium | Yes | Open | [link](audit-stats-uses-fallback-org-id-proposal.md) |
| 16 | `api-keys-cached-by-mcp-auth-in-process-with-no-revocation-bus` | MCP auth caches validated keys 5 min; revocations not propagated | Medium | Yes | Open | [link](api-keys-cached-by-mcp-auth-in-process-with-no-revocation-bus-proposal.md) |
| 17 | `api-key-no-scope-for-mcp-and-no-rate-limit-per-key` | Rate limit is per-IP only; stolen key behind CDN not throttled | Medium | Yes | Open | [link](api-key-no-scope-for-mcp-and-no-rate-limit-per-key-proposal.md) |
| ~~18~~ | ~~`api-key-storage-allows-user-id-null-and-org-id-null`~~ | ~~API keys with `org_id=None`/`"local"` accepted in cloud mode~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (covered by #8 fix — creation and validation both reject invalid org_id) | [link](api-key-storage-allows-user-id-null-and-org-id-null-proposal.md) |
| ~~19~~ | ~~`sql-validation-bypass-via-cte-or-set-op-with-non-select-leaf`~~ | ~~SELECT-only validator may permit dangerous dialect functions~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (79+ function denylist across 7 dialects) | [link](sql-validation-bypass-via-cte-or-set-op-with-non-select-leaf-proposal.md) |
| ~~21~~ | ~~`inject-limit-fallback-string-concat-on-parse-failure`~~ | ~~`inject_limit` falls back to string concatenation on parse failure~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (raises ValueError; callers return 400) | [link](inject-limit-fallback-string-concat-on-parse-failure-proposal.md) |
| 23 | `dbt-profiles-yml-written-with-plaintext-credentials` | `_create_new_project` writes plaintext credentials to `profiles.yml` | Medium | Partial | Open (deprioritized — feature disabled) | [link](dbt-profiles-yml-written-with-plaintext-credentials-proposal.md) |
| 24 | `connection-test-tcp-connect-toctou-vs-ssrf-check` | DNS rebinding window between SSRF check and `socket.connect` | Medium | Yes | Open | [link](connection-test-tcp-connect-toctou-vs-ssrf-check-proposal.md) |
| 25 | `bigquery-and-snowflake-skip-ssrf-validation` | Cloud warehouse connectors excluded from SSRF validation | Medium | Yes | Open | [link](bigquery-and-snowflake-skip-ssrf-validation-proposal.md) |
| 26 | `sandbox-mounts-host-data-volume-readonly-but-broad` | Sandbox container mounts entire user home directory by default | Medium | Partial | Open (deprioritized — feature disabled) | [link](sandbox-mounts-host-data-volume-readonly-but-broad-proposal.md) |
| ~~27~~ | ~~`sandbox-execute-no-tenant-binding`~~ | ~~Sandbox manager `/execute` has no authentication~~ | ~~Medium~~ | ~~Partial~~ | **Fixed** (X-Sandbox-Auth shared secret) | [link](sandbox-execute-no-tenant-binding-proposal.md) |
| ~~29~~ | ~~`sandbox-output-html-rendered-with-dangerously-set-inner-html`~~ | ~~Sandbox HTML output rendered via `dangerouslySetInnerHTML`~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (DOMPurify with strict allowlist) | [link](sandbox-output-html-rendered-with-dangerously-set-inner-html-proposal.md) |
| ~~33~~ | ~~`localStorage-stores-api-key-vulnerable-to-xss`~~ | ~~API key persisted in `localStorage` — exfiltratable by XSS~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (moved to sessionStorage; cloud mode clears) | [link](localstorage-stores-api-key-vulnerable-to-xss-proposal.md) |
| ~~38~~ | ~~`dockerfile-gateway-runs-as-root`~~ | ~~`Dockerfile.gateway` runs uvicorn as UID 0~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (non-root UID 10001) | [link](dockerfile-gateway-runs-as-root-proposal.md) |
| ~~40~~ | ~~`sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt`~~ | ~~Passphrase salt derived from passphrase itself defeats salting~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (SP_ENCRYPTION_SALT env; legacy fallback for migration) | [link](sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt-proposal.md) |
| ~~42~~ | ~~`cors-allow-credentials-true-with-permissive-origin-list`~~ | ~~`allow_credentials=True` with origins from env var including localhost~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (cloud mode enforces HTTPS-only origins) | [link](cors-allow-credentials-true-with-permissive-origin-list-proposal.md) |
| 43 | `mcp-mounted-at-root-instead-of-mcp-prefix-only` | MCP ASGI app mounted at `/` instead of `/mcp` | Medium | Yes | Open | [link](mcp-mounted-at-root-instead-of-mcp-prefix-only-proposal.md) |
| 45 | `audit-log-stores-full-sql-text-including-pii` | Audit log stores full SQL including PII literal values | Medium | Yes | Open | [link](audit-log-stores-full-sql-text-including-pii-proposal.md) |
| 47 | `plugin-is-a-git-submodule-trusted-implicitly` | `plugin/` submodule installed without verification or pinning | Medium | Yes | Open | [link](plugin-is-a-git-submodule-trusted-implicitly-proposal.md) |
| 50 | `auth-rate-limit-per-ip-only-allows-key-brute-force-from-many-ips` | No per-key brute-force limiter for auth failures | Medium | Yes | Open | [link](auth-rate-limit-per-ip-only-allows-key-brute-force-from-many-ips-proposal.md) |
| 52 | `billing-page-references-stripe-but-no-webhook-route-found` | Stripe webhook handler missing from repo | Medium | Yes | Open | [link](billing-page-references-stripe-but-no-webhook-route-found-proposal.md) |
| ~~60~~ | ~~`mcp-xff-uses-leftmost-spoofable-by-attacker`~~ | ~~MCP audit log trusts attacker-controlled leftmost X-Forwarded-For~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (switched to rightmost IP) | [link](mcp-xff-uses-leftmost-spoofable-by-attacker-proposal.md) |
| 61 | `dbt-cloud-discover-host-ssrf` | `POST /api/dbt-cloud/projects` SSRFs gateway via user-supplied `host` | Medium | Yes | Open (deprioritized — feature disabled) | [link](dbt-cloud-discover-host-ssrf-proposal.md) |
| 62 | `sandbox-container-runs-with-elevated-caps-and-no-apparmor` | Sandbox container has `SYS_ADMIN`/`SYS_PTRACE` and `apparmor:unconfined` | Medium | Partial | Open (deprioritized — feature disabled) | [link](sandbox-container-runs-with-elevated-caps-and-no-apparmor-proposal.md) |
| ~~56~~ | ~~`cloud-mode-disables-sandbox-but-mcp-server-still-exposes-execute-code-tool`~~ | ~~MCP `execute_code` tool gated by `if not _is_cloud:`~~ | ~~Medium~~ | ~~Yes~~ | **Fixed** (deprioritized — feature disabled) | [link](cloud-mode-disables-sandbox-but-mcp-server-still-exposes-execute-code-tool-proposal.md) |
| 3 | `clerk-jwks-fetched-without-tls-pinning-or-failure-policy` | JWKS client has no failure-mode policy | Low | Yes | Open | [link](clerk-jwks-fetched-without-tls-pinning-or-failure-policy-proposal.md) |
| 4 | `clerk-publishable-key-derives-issuer-via-base64` | Issuer derivation from publishable key fails at runtime not startup | Low | Yes | Open | [link](clerk-publishable-key-derives-issuer-via-base64-proposal.md) |
| 13 | `byok-key-id-cross-tenant-confusion-on-rotate` | BYOK rotate accepts attacker-controlled `new_key_id` without org filter in query | Low | Yes | Open | [link](byok-key-id-cross-tenant-confusion-on-rotate-proposal.md) |
| 14 | `api-key-prefix-too-short-and-collidable` | API key prefix only 7 chars; enables enumeration | Low | Yes | Open | [link](api-key-prefix-too-short-and-collidable-proposal.md) |
| 20 | `sql-stacking-detection-regex-not-aware-of-string-literals` | Stacking detector regex not string-literal-aware | Low | Yes | Open | [link](sql-stacking-detection-regex-not-aware-of-string-literals-proposal.md) |
| 22 | `connector-credentials-extras-include-plaintext-password-twice` | Password stored in `extras_enc` JSON in addition to connection string | Low | Yes | Open | [link](connector-credentials-extras-include-plaintext-password-twice-proposal.md) |
| 28 | `sandbox-mount-extension-allowlist-trivially-bypassed` | `.tar.gz` files classified as `.gz` only; allowlist incomplete | Low | Partial | Open (deprioritized — feature disabled) | [link](sandbox-mount-extension-allowlist-trivially-bypassed-proposal.md) |
| 30 | `sandbox-audit-log-leaks-client-ip-but-not-org-id` | Sandbox audit logs omit `org_id`/`key_id` correlation | Low | Partial | Open (deprioritized — feature disabled) | [link](sandbox-audit-log-leaks-client-ip-but-not-org-id-proposal.md) |
| 32 | `local-key-route-exposes-key-without-auth-in-local-mode` | `/api/local-key` has no auth and no cloud-mode guard | Low | Partial | Open | [link](local-key-route-exposes-key-without-auth-in-local-mode-proposal.md) |
| 34 | `csp-connect-src-includes-arbitrary-backend-url` | CSP `connect-src` computed from unvalidated env var | Low | Yes | Open | [link](csp-connect-src-includes-arbitrary-backend-url-proposal.md) |
| 36 | `enterprise-route-does-not-enforce-org-admin` | `GET /api/team/enterprise` has no Clerk auth check | Low | Yes | Open | [link](enterprise-route-does-not-enforce-org-admin-proposal.md) |
| 37 | `docker-compose-default-postgres-credentials` | `docker-compose.yml` ships weak default Postgres credentials | Low | Partial | Open | [link](docker-compose-default-postgres-credentials-proposal.md) |
| 39 | `clerk-secret-key-required-but-not-validated-at-startup` | Missing `CLERK_PUBLISHABLE_KEY` logs error instead of failing startup | Low | Yes | Open | [link](clerk-secret-key-required-but-not-validated-at-startup-proposal.md) |
| 41 | `legacy-sha256-key-derivation-fallback-still-present` | Legacy SHA-256 decryption fallback increases attack surface | Low | Yes | Open | [link](legacy-sha256-key-derivation-fallback-still-present-proposal.md) |
| ~~46~~ | ~~`client-ip-trust-x-forwarded-for-without-trusted-proxy-list`~~ | ~~X-Forwarded-For honored without trusted proxy validation~~ | ~~Low~~ | ~~Yes~~ | **Fixed** (unified to rightmost IP; see also #60) | [link](client-ip-trust-x-forwarded-for-without-trusted-proxy-list-proposal.md) |
| 48 | `package-lock-no-overrides-and-no-audit-step-in-ci` | No npm audit gate in CI; empty overrides | Low | Yes | Open | [link](package-lock-no-overrides-and-no-audit-step-in-ci-proposal.md) |
| 49 | `pip-install-no-hashes-in-dockerfile` | `pip install` without `--require-hashes` in Dockerfile | Low | Yes | Open | [link](pip-install-no-hashes-in-dockerfile-proposal.md) |
| 54 | `query-results-not-encrypted-at-rest-after-cache` | Schema/result caches may leak sensitive data via process memory | Low | Yes | Open | [link](query-results-not-encrypted-at-rest-after-cache-proposal.md) |
| 55 | `audit-export-streams-without-row-cap` | `POST /api/audit/export` may stream unbounded rows | Low | Yes | Open | [link](audit-export-streams-without-row-cap-proposal.md) |
| 57 | `byok-aws-config-passed-as-json-env-var` | AWS credentials in JSON env var instead of IAM role | Low | Yes | Open | [link](byok-aws-config-passed-as-json-env-id-proposal.md) |
| 63 | `audit-export-row-cap-1m-effectively-unbounded` | Hard-coded `limit=1_000_000` materializes export in memory | Low | Yes | Open | [link](audit-export-row-cap-1m-effectively-unbounded-proposal.md) |
| 64 | `billing-checkout-success-cancel-url-open-redirect-risk` | `success_url`/`cancel_url` forwarded to Stripe unvalidated | Low | Yes | Open | [link](billing-checkout-success-cancel-url-open-redirect-risk-proposal.md) |
| 65 | `unmatched-paths-fall-through-to-mcp-app` | MCP mounted at `/` so unmatched paths leak to MCP | Low | Yes | Open | [link](unmatched-paths-fall-through-to-mcp-app-proposal.md) |
| 66 | `shared-volume-leaks-local-api-key-between-containers` | `signalpilot-shared` volume carries plaintext local key | Low | No | Open (deprioritized — feature disabled) | [link](shared-volume-leaks-local-api-key-between-containers-proposal.md) |
| ~~44~~ | ~~`request-correlation-header-not-validated`~~ | ~~`X-Request-ID` validation already in place; residual log-volume concern~~ | ~~Info (was Low)~~ | ~~Yes~~ | **Fixed** (regex pattern updated to include `_` and `.`) | [link](request-correlation-header-not-validated-proposal.md) |
| 6 | `enterprise-sso-route-stub-returns-empty` | `GET /api/team/enterprise` is a no-op stub | Info | No | Open | [link](enterprise-sso-route-stub-returns-empty-proposal.md) |
| 15 | `api-key-entropy-128-bits-fine-but-no-pepper` | API key hash uses bare SHA-256 with no HMAC/pepper | Info | Yes | Open | [link](api-key-entropy-128-bits-fine-but-no-pepper-proposal.md) |
| 35 | `next-config-does-not-set-security-headers` | `next.config.ts` missing security hardening options | Info | Yes | Open | [link](next-config-does-not-set-security-headers-proposal.md) |
| 51 | `request-body-2mb-limit-may-allow-large-sql-payloads` | 2 MB body limit vs. 100 KB SQL cap — intentional but undocumented | Info | Yes | Open | [link](request-body-2mb-limit-may-allow-large-sql-payloads-proposal.md) |
| 53 | `ci-not-in-repo-cannot-audit` | No `.github/workflows/` in repo — CI/CD security cannot be assessed | Info | Yes | Open | [link](ci-not-in-repo-cannot-audit-proposal.md) |
| 58 | `clerk-research-mentions-dev-keys-endless-fly-19` | `enterprise-connections.md` references dev hostname; not in code | Info | Partial | Open | [link](clerk-research-mentions-dev-keys-endless-fly-19-proposal.md) |
| 67 | `options-method-bypasses-rate-limit-and-body-size` | OPTIONS preflight skips three middlewares | Info | Yes | Open | [link](options-method-bypasses-rate-limit-and-body-size-proposal.md) |
| 68 | `last-used-at-leakage-via-list-api-keys` | `last_used_at` returned per-key + per-request UPDATE write amplification | Info | Yes | Open | [link](last-used-at-leakage-via-list-api-keys-proposal.md) |

---

## Deprioritized scope (2026-04-30)

The owner has disabled the **sandbox** feature (sandbox containers, `/execute`, sandbox UI, MCP `execute_code` tool, host-data mounts, shared-volume key plumbing) and the **project / project-import** feature (git-clone-based project creation, dbt Cloud project discovery, dbt `profiles.yml` materialization) in the cloud deployment as of 2026-04-30, and is not actively maintaining them. Treat the findings below as **low priority** until those features are re-enabled. Severity ratings are retained as-is — they reflect the technical risk that would resurface the moment the feature is turned back on.

Sandbox-related findings:

- #9 `sandboxes-store-not-org-scoped`
- #26 `sandbox-mounts-host-data-volume-readonly-but-broad`
- #27 `sandbox-execute-no-tenant-binding`
- #28 `sandbox-mount-extension-allowlist-trivially-bypassed`
- #29 `sandbox-output-html-rendered-with-dangerously-set-inner-html`
- #30 `sandbox-audit-log-leaks-client-ip-but-not-org-id`
- #56 `cloud-mode-disables-sandbox-but-mcp-server-still-exposes-execute-code-tool` (already Fixed)
- #62 `sandbox-container-runs-with-elevated-caps-and-no-apparmor`
- #66 `shared-volume-leaks-local-api-key-between-containers`

Project / project-import findings:

- #23 `dbt-profiles-yml-written-with-plaintext-credentials`
- #59 `git-clone-arg-injection-via-project-import`
- #61 `dbt-cloud-discover-host-ssrf`

When either feature is reactivated, lift the deprioritized status and triage these findings against the severity column normally.

---

## Round 2 verification annotations

- **#44 `request-correlation-header-not-validated`** — STALE/Mostly fixed. `correlation.py:23-26` validates with `_REQUEST_ID_PATTERN = re.compile(r"[a-zA-Z0-9\-]{1,64}")` using `fullmatch`, so newline/log-injection vectors described in the original proposal are blocked. Severity demoted from Low to Info. The residual concern (clients can echo arbitrary 64-byte tokens into logs as a low-amplification probe) is real but not exploitable. Original proposal retained for context.
- **#56 `cloud-mode-disables-sandbox-but-mcp-server-still-exposes-execute-code-tool`** — FIXED. `mcp_server.py:306` wraps the `execute_code` tool registration in `if not _is_cloud:`. Same pattern at lines 529, 1026, 1182. The MCP tool registry no longer advertises `execute_code` in cloud builds. Original proposal retained as a record of the original concern; severity icon kept for sort stability.
- **#46 `client-ip-trust-x-forwarded-for-without-trusted-proxy-list`** — VALID. New finding #60 is a companion: it documents that `mcp_auth.py` picks the *leftmost* (attacker-controlled) XFF entry while `middleware.py` picks the rightmost. The two findings should be remediated together via a shared helper.
- All other round-1 findings re-verified VALID against current source.

See `/tmp/round-2/audit-verification.md` for the full per-finding verification table.

---

## Findings count by severity

| Severity | Total | Fixed | Open | Notes |
|----------|-------|-------|------|-------|
| Critical | 1 | **1** | 0 | ~~#7~~ |
| High | 6 | **5** | 1 | ~~#1, #8, #9, #10, #31~~; open: #59 (deprioritized) |
| Medium | 27 | **12** | 15 | ~~#11, #18, #19, #21, #27, #29, #33, #38, #40, #42, #56, #60~~; 7 of 15 open are deprioritized |
| Low | 23 | **2** | 21 | ~~#44, #46~~; 4 of 21 open are deprioritized |
| Info | 9 | 0 | 9 | |
| **Total** | **68** | **20** | **48** | 20 fixed, 48 open (11 deprioritized = **37 actionable**) |

---

## Out-of-scope notes

- Binary review of the `runsc` (gVisor) runtime was not performed.
- Third-party JavaScript supply chain was not audited beyond `package-lock.json` lockfile inspection.
- SOC 2 controls, organizational policies, and pen-test of the live cloud environment were not assessed.
- Stripe/billing webhook implementation is flagged as findings #52 and #64 but cannot be fully assessed because no handler exists in the repo.
- AWS/GCP/Azure account-level IAM configuration is out of scope.
- Infra-as-code (Terraform/Pulumi) is not present in the repo.

---

## Methodology appendix

**Round 1 reviewed (carried forward to round 2):**
- `signalpilot/gateway/gateway/auth.py`, `mcp_auth.py`, `middleware.py`, `scope_guard.py`, `store.py`, `main.py`, `network_validation.py`, `deployment.py`, `correlation.py`
- `signalpilot/gateway/gateway/api/{keys,connections,query,sandboxes,files,byok,settings,security,audit,projects}.py`
- `signalpilot/gateway/gateway/engine/__init__.py`, `dbt/validator.py`, `project_store.py`, `mcp_server.py`
- `signalpilot/web/middleware.ts`, `next.config.ts`, `app/layout.tsx`, `app/api/local-key/route.ts`, `app/api/team/enterprise/route.ts`, `lib/api.ts`, `lib/backend-client.ts`, `lib/auth-context.tsx`, `app/sandboxes/[id]/page.tsx`
- `Dockerfile.gateway`, `Dockerfile.sandbox`, `Dockerfile.web`, `docker-compose.yml`
- `sp-sandbox/sandbox_manager.py`, `audit.py`, `sandbox_exec.sh`, `executor.py`
- `signalpilot/web/clerk-research.md`, `enterprise-connections.md`

**Round 2 added file reviews:**
- `signalpilot/gateway/gateway/project_store.py` (full read for git clone path)
- `signalpilot/gateway/gateway/api/projects.py` (full read — dbt Cloud SSRF)
- `signalpilot/gateway/gateway/correlation.py` (verification of #44)
- `signalpilot/gateway/gateway/dbt/validator.py` (subprocess hardening review)
- `sp-sandbox/executor.py` (subprocess env-stripping review)
- `signalpilot/gateway/gateway/mcp_server.py` (#56 verification)

**NOT reviewed:**
- Stripe billing handler (not found in repo)
- CI/CD pipelines (no `.github/workflows/` found)
- AWS/GCP/Azure account or IAM configuration
- Network-level firewall rules and ingress controller configuration
- gVisor runtime binary
