# Security Audit — Full App (runtime), 2026-07-29

Scope: whole-app audit of the deployed gateway + web app (not a diff). Five
parallel passes: auth/session, authorization/IDOR, SQL governance & connectors,
secrets/BYOK, and the Next.js frontend. Every Critical/High was verified in
code; the SQL findings were reproduced by executing the repo's own
`validate_sql` / `inject_limit` against candidate bypasses (sqlglot 30.8.0).

This complements the diff-based audit in `backend-audit.md` /
`frontend-audit.md` / `secrets-and-private-docs.md` — it corroborates the
eval-runner RCE and adds runtime authorization + connector-governance findings
those passes did not cover.

A second round (below, "Round 2 — net-new surfaces") extended coverage into
surfaces the diff audit and Round 1 did not reach: the standalone
notebook-server service, the dbt/notebook proxy layer, and the
analysis-delivery / rendering + BYOS-sandbox path. It found one additional
Critical (unauthenticated dbt router → RCE in the notebook-server) plus five
lower findings.

## Severity tally (Round 1)

| Severity | Count |
|----------|------:|
| CRITICAL | 4 |
| HIGH     | 8 |
| MEDIUM   | 13 |
| LOW      | 6 |

## The authorization root cause (drives several Criticals/Highs)

`gateway/security/scope_guard.py:57-61` — `require_scopes()` returns immediately
and **grants all scopes** when `request.state.auth is None`, which is exactly the
Clerk-JWT / cookie case for every browser user (`http/middleware/auth.py:78-84`
never sets it). So `RequireScope("admin")` degrades to "is authenticated" for
browser users; the only working role gate is the separate `OrgAdmin` dependency.

Its mirror, `gateway/auth/user.py:340-343`, returns `"admin"` for *any* API key
regardless of scopes, so a read-only key passes every `OrgAdmin` gate. Each gate
is blind on the path the other covers.

Durable fix (closes the whole cluster): make `RequireScope("admin")` itself
depend on the org-role check, and derive API-key role from the key's own scopes
(as `mcp/context.py:62-73` already does).

Note: the earlier "26/208 routes gated" claim is **stale** — 199/207 routes now
carry `RequireScope`; the 7 ungated ones are intentional and HMAC-protected. The
problem is that the admin gate doesn't enforce, not that gates are missing.

## Critical

1. **Governance-pipeline bypass in `compare_join_types`** —
   `mcp/tools/model_verify.py:615-698`. `join_keys` and `where_clause` are free
   text, checked only for non-emptiness/size, then interpolated verbatim into SQL
   and executed with **no `validate_sql`, no `inject_limit`, no denylist**. On
   MSSQL this executes stacked DDL/DML (`1=1; DROP TABLE users --`); on Postgres
   it runs `pg_read_file` / `dblink` — exactly what the governed path blocks.
   Reachable via prompt injection into agent-read content, not just a malicious
   user. Fix: route the constructed SQL through `validate_sql` + `inject_limit`;
   constrain `join_keys` to a `col = col` grammar and parse `where_clause` as a
   predicate with the dangerous-function walker applied.

2. **Credential export gated by a no-op** — `api/connections/porting.py:38-39`.
   `POST /connections/export` protects credentials with
   `require_scopes(request,"admin")` (no-op for JWT users). Any `basic_member`
   POSTs `{"include_credentials":true,"confirm":true}` and receives every DB
   password, PAT, and SSH private key in the org. Sibling routes use
   `_role: OrgAdmin` correctly. **One-line fix: add `_role: OrgAdmin`.**

3. **Cross-tenant GitHub token minting** — `api/github.py:72-133`.
   `installation_id` is a raw query param never bound to the caller; the
   app-level JWT mints an installation token for any (small sequential) ID and
   stores it under the attacker's org → cross-tenant private-repo read **and
   write** (`github.py:305`). Fix: exchange `code` for a user token; require
   `installation_id ∈ the caller's installations`.

4. **Eval-config → host RCE** — `api/eval_runs.py:52` + `evals/runner.py`.
   `PUT /evals/config` is global (no org key), gated only by the no-op admin
   scope. Any authenticated user rewrites `repo_url`; the next run clones it and
   posts to the **host Docker socket** with attacker-controlled image and rw
   binds → host-root RCE. (Same RCE the diff audit flagged as HIGH from the
   admin-manifest angle; the missing-authz angle makes it tenant-reachable.)
   Fix: per-org config; gate `/api/evals/*` on a staff role, not a
   tenant-issuable scope.

## High

- **~24 "admin" endpoints reachable by any org member** (audit-log export, eval
  start, knowledge approve, schema-watches, reports) — root cause above; add
  `OrgAdmin`.
- **SSRF re-validation missing at connect time** — `pool_manager.py:309`
  re-resolves the hostname on every query with no validation (TOCTOU / DNS
  rebinding); `connections/testing.py:128` also swallows the SSRF rejection with
  `except ValueError: validated_ips=[host]`. Reachable via `snowflake_host` →
  internal port scan + `169.254.169.254`. Fail closed; re-validate in `acquire`.
- **No dangerous-function denylist for MSSQL / Redshift / Databricks / Trino** —
  `engine/denylists.py` has no `tsql` key, so `OPENROWSET` / `OPENDATASOURCE` /
  `OPENQUERY` (SSRF + credential relay + linked-server pivot) pass (verified
  live). Make unknown-dialect lookup fail closed to the union of all sets.
- **DuckDB path/URL-as-table bypass** — the `read_csv` function denylist is
  decorative; `FROM 'https://evil.com/x.parquet'` and `FROM "/etc/passwd"` pass
  (verified). `read_only=True` doesn't stop external access. Set
  `enable_external_access=false`; reject file-like table names.
- **LIMIT injection silently no-ops** — `engine/transforms.py:47-59` fails open
  on `LIMIT ALL`, `TOP 100 PERCENT`, `FETCH FIRST`, subquery limits (all
  verified unbounded). Gateway buffers all rows in memory → exfiltration + OOM.
  Overwrite unconditionally; add a hard post-execution row cap.
- **BYOK is nominal** — `api/byok.py` stores per-org KMS ARNs but encrypt/decrypt
  uses one process-wide provider from env (`make_provider_for_key` is called only
  in tests). Tenants with their own KMS key have credentials wrapped by the
  operator's key while `validate` returns `{"valid":true}` — misreported custody.
- **TLS client private keys stored plaintext and returned on read scope** —
  `store/store.py:180` writes `ssl_config` (incl. `client_key` PEM) verbatim into
  a plaintext column despite the `ssh_tunnel` path stripping secrets; flows out
  through `GET /api/connections` (read scope). Strip cert/key before persist +
  response.
- **Cross-tenant eval transcripts** — `evals/runner.py:70` run state has no org
  dimension; `GET /api/evals/runs` lists every tenant's runs and SQL.

## Medium

Semantic models keyed by connection name only → cross-tenant glossary poisoning
(`schema/_semantic_store.py:9`); chat traces org-scoped but not user-scoped
(`store/chat_traces.py:23`); `clone_connection` skips `OrgAdmin` + validation +
limits (`crud.py:209`); MSSQL "read-only" is just `READ COMMITTED` = no write
protection, with a misleading comment (`drivers/mssql.py:145`); Postgres
`SET LOCAL statement_timeout` issued outside its transaction = no-op
(`drivers/postgres.py:166`); org `blocked_tables` not enforced on the MCP path
(`mcp/tools/query.py:62`); blocked-table matching is bare-name only so
`public.secrets` entries silently never match (verified); DEK cache never
invalidated on key rotation — wrong cache key (`byok/provider.py:456`); local
BYOK key files written world-readable (`byok/provider.py:118`); user Anthropic
keys injected as plaintext pod env vars (`orchestrator/kubernetes.py:132`); Clerk
JWT audience/`azp` unverified by default (`auth/user.py:153`); open redirect via
`"/\evil.com"` in notion/slack callbacks; local mode is the unauthenticated
default when `SP_DEPLOYMENT_MODE` is unset.

## Low

Notebook session JWTs are unrevocable 8h bearer tokens with no session-status
recheck (`auth/user.py:109`); MCP client-IP trusts attacker-controlled
`X-Real-IP`, defeating the auth limiter (`auth/mcp_api_key.py:334`); rate-limit
tiers wired ~80x looser than documented (`main.py:501`); gzip bomb decompressed
before size check (`git/http_server.py:167`); BigQuery/SQLite identifier escaping
dialect-wrong (not currently reachable) (`schema/_identifiers.py`,
`drivers/sqlite.py:122`); pool keys global — first caller's credential extras win
(`pool_manager.py:228`).

## Reclassified after review (NOT a finding at prod severity)

- **Committed Fernet key in `docker-compose.yml:55`** — initially flagged
  Critical, **downgraded to LOW (dev-default hygiene)**. `docker-compose.yml` is
  the labeled *Local Development Stack*; `store/crypto.py:_get_encryption_key()`
  **raises `RuntimeError` in cloud mode if `SP_ENCRYPTION_KEY` is unset** and
  never falls back to a committed default; the key appears in none of the prod
  paths (`docker-compose.k8s.yml`, `deploy/`, `k3s.yaml`), which inject it as a
  secret. It is a starter key for local self-hosters, not the prod key. Residual
  risk: a self-hoster who runs the local stack unchanged inherits a public key —
  add a warning comment beside it (same recommendation the diff audit made for
  the MinIO defaults). `POSTGRES_PASSWORD: changeme_dev_only` and
  `minioadmin/minioadmin` in the same file are dev defaults on the same footing.
- `.env.local` `XATA_KEY` is gitignored and clean of history — on-disk cleartext,
  rotate as hygiene, not a committed-secret incident.

## Verified clean

Store layer is uniformly org-scoped (no IDOR; refuses to build a query without an
`org_id` filter in cloud mode; no method accepts a caller-supplied `org_id`).
JWT: algorithm pinned from header before decode, `alg=none` and key-confusion
closed, `exp/iat/sub` required. Credential crypto is Fernet AEAD with no fallback
key in cloud mode; API keys stored as SHA-256 hashes with `hmac.compare_digest`.
Frontend: the one `dangerouslySetInnerHTML` is DOMPurify-sanitized, no secrets in
`NEXT_PUBLIC_*`, CSP/HSTS/`frame-ancestors` set correctly. The recently-changed
`demo-db` path is among the best-secured surfaces (write scope + OrgAdmin + plan
limits + gateway-side Xata key). SQL stacking, null-byte, and Postgres
dangerous-function detection resisted every bypass tried. OAuth/webhook entry
points use constant-time HMAC.

## Suggested fix order

1. `compare_join_types` governance routing (#1).
2. Two one-line `_role: OrgAdmin` additions — porting export (#2), clone.
3. The `scope_guard` / `resolve_org_role` root-cause fix (closes the admin-gate
   cluster).
4. Eval-config isolation (#4).
5. SSRF fail-closed (`except ValueError` in `testing.py`) + connect-time
   re-validation.
6. Add `tsql`/DuckDB denylist entries + fail-closed unknown-dialect lookup.

---

# Round 2 — net-new surfaces (notebook-server, proxies, delivery)

A second pass targeted the surfaces neither the diff audit nor Round 1 covered,
told to report only issues NOT already documented. All verified in code.

## Critical

**R2-1 — The notebook-server `dbt` router is entirely unauthenticated → RCE.**
`notebook-server/signalpilot/_server/api/endpoints/dbt.py` — all 9 handlers
(`/command`, `/clone_project`, `/scaffold_project`, `/compile_model`,
`/preview_model`, `/discover_projects`, `/project_info`, `/models`, `/artifact`)
carry **no `@requires` decorator**, unlike every sibling router
(`datasources.py`, files, git, execution all use `@requires("edit")` — verified
by decorator diff). The service's `AuthBackend.authenticate()`
(`middleware.py:86-113`) returns `None` on a missing/failed token, which
Starlette turns into `UnauthenticatedUser` but does **not** reject — the request
still reaches the handler. Enforcement is therefore entirely per-endpoint, and
these endpoints have none.
- `POST /api/dbt/command` runs `dbt` with attacker-controlled `command`/`args`/
  `project_dir`/`profiles_dir`. dbt is an arbitrary-code engine (Jinja macros,
  `on-run-start`/`on-run-end` hooks, adapter Python) — pointing it at a hostile
  project is code execution as the server user. The `DBT_COMMANDS` allowlist
  (`runner.py:20`) is defined but never enforced.
- `POST /api/dbt/clone_project` passes attacker-controlled `git_url`/`target_dir`
  to `git clone`: SSRF, arbitrary file write (unconstrained `target_dir`), and
  RCE via git's `ext::sh -c …` transport / `file://` exfiltration.
- `POST /api/dbt/scaffold_project` writes `dbt_project.yml`/`profiles.yml`/`.py`
  under attacker-controlled `parent_dir`/`project_name` (joined directly →
  traversal) → arbitrary file/dir write.
- Chained: clone hostile repo → `/command run` → guaranteed RCE. In RUN
  (read-only) mode this is also a clean read→exec privilege escalation, since a
  `read`-scope holder reaches operations every sibling gates behind `edit`.
- Fix: add `@requires("edit")` to all dbt handlers; enforce the `DBT_COMMANDS`
  allowlist; confine `project_dir`/`target_dir` to a workspace root; reject
  non-http(s) git schemes (`ext::`, `file://`, `ssh://`) in `clone_git_repo`.

## High

**R2-2 — The notebook-server `agent` router is unauthenticated (agent-driven
RCE).** `endpoints/agent.py` — beyond the already-known `/save-api-key`, none of
`/create`, `/message`, `/stop`, `/status`, `/list`, `/events` carry `@requires`.
`/message` (`agent.py:184-237`) drives a tool-enabled Claude agent (file +
execution tools) with attacker-controlled `message` and a `cwd` taken from the
`x-gateway-project-id` / `x-gateway-branch-id` request headers. Fix: gate the
whole agent router behind `@requires("edit")`.

**R2-3 — SSRF with readable exfiltration via analysis-delivery snapshot URL
passthrough.** `notion/analysis.py:727-752` (`_internal_signalpilot_url`) returns
absolute URLs unchanged (and returns `url` verbatim when `runtime is None`);
`_snapshot_fetcher` (`:800-811`) then `client.get(fetch_url)` and returns the
JSON straight into the HTML-orchestrator payload that gets rendered into the
report the user reads. Snapshot URLs originate from worker/trace data, not a
signed gateway origin, so a `dataSnapshots[].url` of
`http://169.254.169.254/latest/meta-data/…` is fetched server-side and its
response rendered back to the reader — a readable exfil channel, not blind SSRF.
(The chart path `_fetch_chart_image` at `:947` is constrained to `image/*`, so
blind only.) Fix: reject `is_absolute and not is_internal and not is_public`
instead of passing through; refuse when `runtime is None`; add an egress
allowlist blocking loopback/link-local/private ranges.

## Medium

**R2-4 — `/api/files/browse` enumerates the host filesystem.** `api/files.py:13-25`
forwards a caller-supplied `path` (capped only at 4096 chars) and `pattern` to
the sandbox manager's `/files` endpoint, gated by `RequireScope("read")` with no
root confinement or traversal check. Any read-scope key can call
`GET /api/files/browse?path=/&pattern=*` to walk the host filesystem and
enumerate filenames. Fix: confine `path` to a configured base dir (resolve +
assert within root; reject `..`/absolute escapes); require a higher scope.

**R2-5 — `SandboxClient` base_url bypasses the SSRF denylist and leaks the
sandbox token.** `network/sandbox_client.py:27-47` validates only scheme +
hostname-present; it never calls `validate_connection_host()`, despite the URL
being "configurable from the settings page (BYOS)." Every request attaches
`X-Sandbox-Auth: <SP_SANDBOX_TOKEN>` (and per-request session tokens in the
body). A BYOS URL pointed at `169.254.169.254`/internal turns the gateway into an
SSRF primitive that also exfiltrates the sandbox shared secret + session tokens.
Fix: in cloud mode resolve + validate the host through `validate_connection_host`
(as `validate_xata_control_url` already does) before building the client.

**R2-6 — Notebook-proxy `path` not CRLF/charset-validated (asymmetric with the
query check).** `notebook_proxy/routes.py:90-113` validates the WS *query string*
against `_WS_QUERY_SAFE_PATTERN` explicitly to prevent response-splitting, but
the sibling `{path:path}` segment — concatenated into `upstream_url` right below
(`:109`) and into the HTTP upstream URL (`proxy.py:89`) — gets no such check. A
path like `.../<session>/foo%0d%0aHeader:x` decodes to `foo\r\nHeader:x`. httpx
backstops the HTTP side; the WS side depends on the installed `websockets`
version. Defense-in-depth defect regardless. Fix: apply the same safe-charset
gate to `path` in both `proxy_http` and `proxy_websocket`.

## Low

**R2-7 — Notebook-server tokens derived with non-cryptographic builtin `hash()`.**
`tokens.py:31,52` — `AuthToken.from_code` / `SkewProtectionToken.from_code` use
Python's 64-bit builtin `hash()` over the notebook source. To be stable across
instances (their purpose) hash randomization must be off, making them
deterministic and low-entropy — and they are the only barrier in front of R2-1/
R2-2 in RUN mode. Fix: HMAC-SHA256 over the source plus a server secret.

## Round 2 — checked and found sound

dbt_proxy forwarder/session/protocol (16 MiB frame caps, slowloris timeout,
per-session statement/portal caps, DSN-scrubbing error sanitization, fail-closed
`_format_param`); both proxies derive the upstream from server-side state, never
request headers (no open-proxy); outbound header stripping of
Cookie/Authorization/Host/`sec-websocket-*`; delivered-report XSS is mitigated
(sandboxed iframe `allow-scripts` without `allow-same-origin`, gateway never
serves report HTML as `text/html`, `_safe_script_json` escapes `</script>`
breakout); report reads/mutations are org-scoped (no IDOR); notebook-server
`terminal.py` WS validates auth + `cwd`; `assets.py` uses
`validate_inside_directory` + `resolve()`/`relative_to()`; `yaml.safe_load`
throughout, no pickle in this surface.
