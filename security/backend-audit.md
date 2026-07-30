# Backend, MCP, and Infrastructure Security Audit

Audit date: 2026-07-29

## SP-SEC-001 - Scope and organization-role enforcement are inconsistent

**Severity: Critical**

`signalpilot/gateway/gateway/security/scope_guard.py:57-65` grants all scopes
when `request.state.auth` is absent. That is the normal Clerk/JWT path because
`signalpilot/gateway/gateway/http/middleware/auth.py:76-84` deliberately defers
JWT authentication without populating `request.state.auth`. `RequireScope`
verifies the JWT, but `require_scopes` still treats every verified JWT user as
having `admin`.

The inverse mismatch is at
`signalpilot/gateway/gateway/auth/user.py:324-349`: every API key is treated as
an organization admin without checking for an `admin` scope. A write-only API
key can therefore pass routes that combine `RequireScope("write")` with
`OrgAdmin`.

**Remediation:** model organization role and API capability as separate
attributes. Make `RequireScope("admin")` require an actual org-admin or staff
role for JWT users. Derive API-key role from an explicit `admin` scope. Add a
permission matrix test covering basic/admin JWTs and read/write/admin API keys
against every protected route.

## SP-SEC-002 - Basic cloud members can export decrypted connection credentials

**Severity: Critical**

`signalpilot/gateway/gateway/api/connections/porting.py:27-40` protects export
with `write` and calls `require_scopes(request, "admin")` only when credentials
are requested. Because SP-SEC-001 makes that admin check a no-op for JWT users,
an ordinary organization member can request `include_credentials=true`.
Lines 90 onward return decrypted connection strings and SSL configuration for
every connection in the caller's organization.

**Remediation:** add an explicit `OrgAdmin` dependency, keep the admin API scope,
and require a recent reauthentication or one-time export confirmation. Strip
TLS private keys from the response unless a separate, audited credential-export
policy explicitly permits them.

## SP-SEC-003 - `compare_join_types` bypasses governed SQL validation

**Severity: Critical**

`signalpilot/gateway/gateway/mcp/tools/model_verify.py:607-698` accepts free-text
`join_keys` and `where_clause`, interpolates them into multiple query fragments,
and sends the constructed statement directly to `connector.execute`. The imported
`gateway.mcp.validation._validate_sql` checks only non-emptiness and a 100 KB
length; it is not `gateway.engine.validate_sql` and applies no statement,
dangerous-function, table, or limit policy.

An agent can be induced through prompt injection to place a dangerous function
or subquery in a join or predicate. Database read-only settings reduce some
write impact but do not block file reads, network-capable functions, expensive
queries, or data exfiltration.

**Remediation:** parse `join_keys` into a strict list of qualified-column equality
pairs. Parse `where_clause` as an expression and reject statements, subqueries,
comments, and dangerous functions. Route the final SQL through
`gateway.engine.validate_sql` and `inject_limit` before execution. Add adversarial
tests for stacked statements, file/network functions, subqueries, comments, and
tautologies in both inputs.

## SP-SEC-004 - GitHub callback does not bind installation ID to the tenant

**Severity: Critical**

`signalpilot/gateway/gateway/api/github.py:72-130` validates signed state to
choose the destination organization, but accepts `installation_id` independently.
The server's GitHub App JWT then retrieves installation details and creates an
installation token for that caller-supplied ID. No step proves that the
installation was created by the current flow or belongs to the authenticated
tenant. Installation IDs are not an authorization secret.

An authenticated tenant able to obtain another installation ID for the same
GitHub App can store a token for that installation under its own organization and
obtain a credential-bearing clone URL at lines 287-311.

**Remediation:** bind state to user, org, nonce, intended action, and expected
installation. Complete GitHub's user authorization flow and verify that the
installation appears in the authenticated user's accessible installations.
Reject callbacks whose installation owner and repositories do not match the
recorded flow. Store and consume state once.

## SP-SEC-005 - Default compose exposes a fully privileged unauthenticated gateway

**Severity: Critical**

`docker-compose.yml:43-44` publishes gateway port 3300 on every host interface.
`docker-compose.yml:54` selects local deployment mode. In that mode,
`signalpilot/gateway/gateway/http/middleware/auth.py:86-92` accepts a request with
no API key as `local_nokey`, and
`signalpilot/gateway/gateway/security/scope_guard.py:63-65` grants every scope.

Any system that can reach the host port can use query, connection, knowledge,
upload, administrative, MCP, and eval endpoints. A laptop firewall is not an
application security boundary.

**Remediation:** publish `127.0.0.1:3300:3300` for local development. Generate
and require a local API key when the listener is non-loopback. Remove the
unconditional all-scopes path for `local_nokey`. Add a compose integration test
that calls a privileged endpoint from a non-loopback client and expects 401.

## SP-SEC-006 - Eval routes expose cross-tenant infrastructure execution and data

**Severity: Critical**

The eval endpoints at
`signalpilot/gateway/gateway/api/eval_runs.py:42-119` rely on the ineffective
JWT admin scope from SP-SEC-001. Configuration and file-based run state are
global rather than organization-scoped. A basic member can replace `repo_url`,
start a run, and read other tenants' run metadata and SQL transcripts.

`signalpilot/gateway/gateway/evals/runner.py:511-598` lets the selected repository
manifest choose a container image, script, environment file, additional Docker
network, and mounts below the configured setup root. The gateway talks to the
host Docker socket mounted at `docker-compose.yml:120-127`.

The child is not explicitly privileged and does not directly receive the Docker
socket, so unconditional host-root compromise was not demonstrated. It still
provides arbitrary container code execution, access to configured host mounts,
and attachment to Docker networks from a tenant-reachable application route.

**Remediation:** restrict the feature to a separate staff identity. Make config,
run state, and transcripts organization-scoped. Move execution into a dedicated
runner with a constrained job API. Allowlist immutable image digests, fixed
networks, and fixed read-only mounts. Validate repository paths and invoke a fixed
entry point without `sh -lc`.

## SP-SEC-007 - S3 multipart quota is based on client-claimed size

**Severity: High**

`signalpilot/gateway/gateway/api/uploads.py:151-154` accepts a client-supplied
size. The initiate path at lines 187-236 checks that claim and presigns one URL
per part. The signing helper at lines 55-79 does not bind exact content length or
a server-verified checksum to each `UploadPart` request. Lines 260-263 state that
actual object size is checked only after completion.

An authenticated `write` principal can claim a small object, upload much larger
parts, and abandon the multipart upload until lifecycle cleanup. Completing an
oversized object causes deletion only after storage and transfer have been used.

**Remediation:** persist owner-bound upload sessions with expected length, part
plan, checksums, and expiry. Enforce per-principal concurrent bytes and upload
counts. Use short presign expiry, a one-day-or-shorter abort lifecycle, explicit
authenticated abort, and the expensive-operation rate limiter.

## SP-SEC-008 - Stateful MCP transport uses a vulnerable SDK

**Severity: High**

The gateway locks `mcp==1.27.1` at
`signalpilot/gateway/uv.lock:1328-1329`.
`signalpilot/gateway/gateway/mcp/server.py` creates a default stateful FastMCP
instance, and `signalpilot/gateway/gateway/main.py:574-581` mounts Streamable HTTP
behind custom authentication. The middleware validates each request but does not
bind the SDK session ID to the principal.

PYSEC-2026-3482 is relevant: a learned or guessed MCP session ID can be replayed
by a different authenticated principal in affected stateful transports.
PYSEC-2026-3481 and PYSEC-2026-3483 also affect the locked version. Notebook MCP
apps use `stateless_http=True`, so this session reachability does not apply there.

**Remediation:** upgrade every MCP lock to at least `1.28.1`. Until then, use a
stateless transport or bind session ownership before routing. Add a two-principal
session replay test.

## SP-SEC-009 - Kubernetes runtime group has cluster-wide secret and pod access

**Severity: High**

`deploy/k8s/gateway-runtime-rbac.yaml` creates a `ClusterRoleBinding` for the EC2
runtime group. Its `ClusterRole` can create, read, list, patch, and delete pods and
Secrets across the cluster, exec into pods in any namespace, and manage Roles and
RoleBindings. The neighboring admission policy targets tenant notebook namespaces
and does not constrain unrelated namespaces.

**Remediation:** remove cluster-wide Secrets and `pods/exec`. Bind a namespaced
Role only in tenant namespaces. For dynamic namespaces, use a small bootstrap
controller whose admission policy permits bindings only in labeled notebook
namespaces and only to a fixed Role.

## SP-SEC-010 - SSRF checks fail open and are not repeated at connect time

**Severity: High**

`signalpilot/gateway/gateway/api/connections/testing.py:124-135` catches every
`ValueError` from `resolve_and_validate`, including a blocked private or metadata
address, then connects to the original host. This turns the validation rejection
into an SSRF fallback. `signalpilot/gateway/gateway/connectors/pool_manager.py:209-318`
later resolves and connects saved hostnames without re-validating the destination,
leaving a DNS-rebinding window after creation-time checks.

**Remediation:** fail closed on any validation error. Separate unsupported
connection types from security rejection with distinct result types. Resolve and
validate immediately before every new outbound connection, pin the validated
address where the driver permits it, and recheck redirects and tunnel destinations.

## SP-SEC-011 - SQL dangerous-operation checks fail open by dialect

**Severity: High**

`signalpilot/gateway/gateway/engine/denylists.py:32-157` defines dialect sets for
only a subset of supported engines. Lines 197-203 treat an unknown set as empty.
The `mssql` dialect maps to `tsql`, for example, but there is no `tsql` set.
Local reproduction confirmed that a T-SQL `OPENROWSET` query passes
`validate_sql`. Redshift, Databricks, and Trino likewise lack dialect-specific
sets.

DuckDB's function denylist does not catch path-as-table syntax. Local reproduction
confirmed that `SELECT * FROM 'https://example.invalid/x.parquet'` passes. A
read-only database connection does not disable file or network reads.

**Remediation:** define policy for every supported dialect and fail closed when a
dialect has no reviewed policy. Block T-SQL external rowset/data-source operations.
Start DuckDB with `enable_external_access=false` and reject file/URL table forms.
Add real-parser tests for each engine's file, network, linked-server, extension,
and external-query syntax.

## SP-SEC-012 - LIMIT enforcement retains unbounded forms

**Severity: High**

`signalpilot/gateway/gateway/engine/transforms.py:47-59` leaves an existing limit
unchanged when it cannot convert the expression to an integer. Local reproduction
confirmed that PostgreSQL `LIMIT ALL` and `FETCH FIRST 100 ROWS ONLY` remain
unchanged when the configured maximum is 10. The gateway can then buffer results
beyond the intended cap, causing bulk exfiltration or memory exhaustion.

**Remediation:** replace the top-level limit unconditionally with
`min(parsed_limit, max_rows)` and reject unsupported limit forms. Apply an
independent streaming/post-execution hard row cap in every connector so parser or
dialect mistakes cannot return an unbounded result.

## SP-SEC-013 - Tenant BYOK records use one process-wide provider

**Severity: High**

`signalpilot/gateway/gateway/store/byok_state.py` holds one module-level provider.
Store encryption and decryption at
`signalpilot/gateway/gateway/store/store.py:232-264` and `:476-493` resolve a
tenant key row but pass its alias to that single provider. The production factory
can build a provider from each `GatewayBYOKKey`, but application paths do not call
it. The validation endpoint at
`signalpilot/gateway/gateway/api/byok.py:279-396` also tests the process-wide
provider rather than the selected row's provider configuration.

This can report a tenant key as valid while credentials are wrapped by the
operator-configured KMS key, violating the advertised custody boundary.

**Remediation:** instantiate or cache a provider keyed by immutable tenant key ID
and provider configuration. Validate and encrypt with that exact provider. Include
the KMS key identifier in authenticated encryption context and audit records. Add
two-tenant tests using distinct KMS keys.

## SP-SEC-014 - TLS client private keys are stored and returned as metadata

**Severity: High**

`signalpilot/gateway/gateway/store/store.py:169-182` strips SSH secrets before
metadata persistence but stores the full SSL configuration. Update logic at lines
328-330 does the same. `GatewayConnection.to_info_dict` returns `ssl_config`, and
the read-scoped list/get routes expose it. If `client_key` is present, it resides
in a plaintext JSON column and is returned to read principals.

**Remediation:** move TLS certificates and private keys into encrypted credential
extras. Persist only non-secret TLS mode metadata. Redact secret fields from every
response and export unless a separately authorized credential-export operation is
used. Migrate and purge existing plaintext rows.

## SP-SEC-015 - Connection pools can reuse another tenant's credential extras

**Severity: High**

`signalpilot/gateway/gateway/connectors/pool_manager.py:228-275` keys the global
pool only by database type and connection string. It excludes organization ID and
credential extras. If two tenants use the same visible connection string with
different service-account JSON, TLS key, SSH tunnel, or token extras, the second
tenant can receive the connector initialized by the first tenant.

**Remediation:** include a non-secret credential identity/version and org isolation
key in the pool key, or maintain per-org pools. Never hash raw secret values into
logs. Close affected pools on credential rotation and add a two-tenant collision
test.

## SP-SEC-016 - Notebook API-key mutation lacks an endpoint credential

**Severity: Medium**

`signalpilot/notebook-server/signalpilot_notebook_server/agent.py:115-155` accepts
an API key, attempts to persist it through the gateway, and mutates process-global
`os.environ` even when persistence fails. The external notebook proxy authenticates
session ownership and local compose publishes the notebook only on loopback, so a
broad cross-user claim is not supported. Internal pod/container callers can still
reach a tokenless notebook directly.

**Remediation:** require a notebook-scoped session credential, fail closed when
persistence fails, and store per-user state outside process-global environment
variables.

## SP-SEC-017 - Unsigned local webhook and unresolved Bandit gate

**Severity: Medium**

`signalpilot/gateway/gateway/api/github_bot.py:39-49` accepts unsigned GitHub
webhooks in local mode. Combined with SP-SEC-005, a network client can trigger
repository scans and warehouse aggregate queries.

The GitHub Bandit job also reports B608 at
`signalpilot/gateway/gateway/github_bot/scanner.py:100`, `:107`, `:170`, and
`:175`. Manual tracing found strict model-name validation and identifier quoting,
so these appear to be false positives, but they still fail the required gate.

**Remediation:** require a webhook secret whenever the feature is enabled and
disable the route otherwise. Refactor scanner query construction so the quoting
invariant is visible to static analysis, or use narrow documented suppressions
with regression tests.

## Lower-severity hardening

- `signalpilot/gateway/gateway/api/notion.py:612-614` answers subscription
  verification challenges before signature validation. Rate-limit and validate
  the challenge shape.
- Default compose includes a public development encryption key. Prevent it from
  being accepted in shared or cloud deployments.
- GitHub Actions use floating major-version action tags. Pin security-sensitive
  actions to reviewed commit SHAs and update them through controlled automation.
