# SignalPilot Security Audit

Audit date: 2026-07-29 (first round). Last updated: 2026-07-29.

Audited revision: `e77641af` on local branch `feature-sprint-7-22`.

The original findings below were raised against `52c26a8f` on the same branch.
This document tracks each of them through to its current state on `e77641af`.

Scope: application code, MCP surfaces, deployment configuration, browser code,
locked dependencies, CI security controls, and tracked sensitive material.

This is a source review and configuration audit, extended with runtime and
deployment testing during remediation. It is not a penetration test of a
production environment.

## Where the branch stands

The first-round findings have largely been remediated on this branch. The
authorization root cause, the SQL-governance fail-opens, the GitHub
cross-tenant token mint, the unauthenticated compose listener, the
unauthenticated notebook-server `dbt`/`agent` routers, the credential-custody
defects and the cluster-wide Kubernetes RBAC are all fixed, most of them with
executable proof (see Verification).

A second review round then found further issues, several of them Critical, in
surfaces the first round either did not reach or judged sound. Those are being
fixed now; some are complete and some are in progress on this branch at the time
of writing. The branch is not clear for promotion until they land and the
deployment prerequisites below are satisfied.

Two commits on this branch are explicitly **not** part of the security work:
`ed151537` (Postgres/MSSQL schema-introspection and concurrency fixes, whose
authorship is inferred rather than known and which its own message asks to be
confirmed before merge) and `e77641af` (demo-page UI copy).

## Disposition — first round

Finding IDs are from [backend-audit.md](backend-audit.md),
[frontend-audit.md](frontend-audit.md),
[secrets-and-private-docs.md](secrets-and-private-docs.md) and the Round 2
section of [app-runtime-audit-2026-07-29.md](app-runtime-audit-2026-07-29.md).

| ID | Severity | Finding | State |
|---|---|---|---|
| SP-SEC-001 | Critical | Admin scope gate does not enforce an organization role; every API key resolves as admin | **Fixed** `9c4d10da`. Browser-cookie path was separately live and is covered by `9fff7883` + the Playwright suite |
| SP-SEC-002 | Critical | Basic cloud member can export decrypted credentials | **Fixed** `9c4d10da` (`OrgAdmin` on export/import/clone) |
| SP-SEC-003 | Critical | `compare_join_types` bypasses governed SQL validation | **Fixed** `432b6dfe` |
| SP-SEC-004 | Critical | GitHub callback mints another tenant's installation token | **Fixed** `0cad4df5`. **Residual:** installation `permissions` deliberately not narrowed (the product uses contents/PR/issues/statuses writes); repository scope was the reduction made. Requires the deployment prerequisites below |
| SP-SEC-005 | Critical | Default compose exposes an unauthenticated, fully scoped gateway on all interfaces | **Fixed** `8f65c020`. Reproduced from a non-loopback address before the fix; gateway and web now bind `127.0.0.1` |
| SP-SEC-006 | Critical | Eval routes let tenant users drive host Docker workloads; run state is cross-tenant | **In progress on this branch.** Not addressed by any commit listed here; carried into the second round below |
| SP-SEC-007 | High | S3 multipart quota based on client-claimed size | **Residual.** `4d0eec82` binds an exact `ContentLength` per part, adds owner-bound sessions, per-principal ceilings and 30-minute presign expiry. Upload sessions remain in-process — see the second-round entry |
| SP-SEC-008 | High | Stateful MCP transport on a vulnerable SDK | **Fixed** `011114a5` (`mcp` 1.27.1 → 1.29.0, capped below 2.0). **Residual:** 1.29 introduces a ~4 MiB body cap on streamable-HTTP POSTs |
| SP-SEC-009 | High | Kubernetes runtime group holds cluster-wide Secret/pod/exec access | **Fixed** `6de903b2`, validated on a real kind cluster. **Residual:** a namespace-label pivot remains, see the second round. Requires the RBAC migration below |
| SP-SEC-010 | High | SSRF checks fail open and are not repeated at connect time | **Residual.** `a73badc2` re-resolves and re-validates before each connect and removes the `except ValueError` fallback. Validated addresses are deliberately not pinned into the DSN (would break `sslmode=verify-full` and SNI), which leaves the rebinding window the second round re-raises. SSH-tunnel destinations are skipped by design |
| SP-SEC-011 | High | Dangerous-function denylist fails open by dialect | **Fixed** `432b6dfe` (unknown dialects fall back to the union; `tsql`, redshift, databricks, trino added; table-function and path-as-table forms closed). Two gaps were left as strict xfails and are now closed in the second round |
| SP-SEC-012 | High | `LIMIT ALL` / `FETCH FIRST` / parameterised limits unbounded | **Residual.** `432b6dfe` overwrites the top-level limit whenever it cannot be resolved to an integer. The hard post-execution row cap the audit also recommended was not added |
| SP-SEC-013 | High | Tenant BYOK uses one process-wide provider | **Fixed** `a73badc2`. **Residual:** a single narrow retry against the legacy encryption context is kept so pre-existing ciphertexts decrypt |
| SP-SEC-014 | High | TLS client private keys stored plaintext and returned on read scope | **Residual.** `13832508` + `a73badc2` move secrets into encrypted extras and redact reads and export manifests. Existing rows are only migrated by a dry-run-by-default helper that is never invoked automatically |
| SP-SEC-015 | High | Connection pools reuse another tenant's credential extras | **Fixed** `a73badc2` (org + credential-identity in the pool key; cache-hit branch guarded by identity match) |
| SP-SEC-016 | Medium | Notebook API-key mutation lacks an endpoint credential | **Residual.** `8f65c020` gives every notebook a real per-session token and `5e15c4d7` gates the routers, so the endpoint is no longer reachable without credentials. The handler still mutates process-global `os.environ` |
| SP-SEC-017 | Medium | Unsigned local GitHub webhook; unresolved Bandit gate | **Fixed** `4d0eec82` (route disabled without a secret, in every mode) and `011114a5` (B608 refactored behind a validated-quoting helper, generated SQL asserted byte-identical) |
| SP-SEC-018 | High | Web lock contains blocking advisories | **Fixed** `011114a5`, plus the second-round dependency pass below |
| SP-SEC-019 | High | Docs lock contains a critical WebSocket advisory | **Fixed** `011114a5` |
| SP-SEC-020 | Low | CSP permits `unsafe-inline`/`unsafe-eval`; gateway origin in `base-uri` | **Partially fixed / Accepted.** `8f65c020` removes the gateway origin from `base-uri`. `unsafe-eval` is accepted for the Vega/Altair chart stack; `unsafe-inline` and nonce-based script policy remain open |
| SP-SEC-021 | Low | VS Code bridge posts to `"*"` parent origin | **Open.** No matching sensitive receiver exists in this revision |
| SP-SEC-022 | High (confidentiality) | Internal, customer, vendor and legal documents tracked in the repository | **Open — accepted as out of scope for this branch.** See the caveat below |
| R2-1 | Critical | notebook-server `dbt` router entirely unauthenticated → RCE | **Fixed** `5e15c4d7` (auth, `DBT_COMMANDS` allowlist, path confinement, git scheme rejection) and `8f65c020` (the decorators were inert until then — see contradictions) |
| R2-2 | High | notebook-server `agent` router unauthenticated | **Fixed** `5e15c4d7` + `8f65c020` |
| R2-3 | High | Analysis-delivery snapshot URL passthrough (readable SSRF exfiltration) | **Fixed** `4d0eec82` |
| R2-4 | Medium | `/api/files/browse` enumerates the host filesystem | **Fixed** `4d0eec82` (confined to a configured root, raised to write scope) |
| R2-5 | Medium | `SandboxClient` base_url bypasses SSRF denylist and leaks `SP_SANDBOX_TOKEN` | **Fixed** `4d0eec82` for host validation. The second round found a further, separate leak in the same component — see below |
| R2-6 | Medium | Notebook-proxy `path` not charset-validated | **Fixed** `8f65c020` |
| R2-7 | Low | notebook-server tokens derived with builtin `hash()` | **Open.** Materially reduced by `8f65c020`, which puts a real per-session token in front of these routes, but the derivation is unchanged |

The Medium and Low buckets in the Round 1 runtime audit were not tracked
individually. Some were closed incidentally — the DEK cache-invalidation bug and
the global pool key by `a73badc2`, Clerk `azp`/`aud` verification by the
second-round work below. Others remain **Open**: MSSQL "read-only" being only
`READ COMMITTED`, the no-op Postgres `SET LOCAL statement_timeout`, org
`blocked_tables` not enforced on the MCP path, bare-name blocked-table matching,
world-readable local BYOK key files, user Anthropic keys as plaintext pod env
vars, the `"/\evil.com"` open redirect in the Notion/Slack callbacks, and
unrevocable 8-hour notebook session JWTs.

## Disposition — second round

A later review pass over the remediated branch. These are being worked now;
state is recorded as of this writing and several are not finished.

| Severity | Finding | State |
|---|---|---|
| Critical | Eval runner reachable by tenant admins, with host Docker socket access; eval config and run state are process-global rather than organization-scoped | **In progress on this branch.** This is SP-SEC-006, still open |
| Critical | A process-wide sandbox client singleton leaked the platform `SP_SANDBOX_TOKEN` to tenant-configured endpoints, and let one tenant's configured endpoint serve another tenant's requests | **Fixed** — per-org clients; the platform token is no longer sent to tenant BYOS endpoints. Makes `SP_SANDBOX_MANAGER_URL` security-relevant, see prerequisites |
| Critical | Kubernetes namespace-label pivot: the gateway holds `namespaces: patch`, and admission does not govern namespace *updates*, so the gateway could label `kube-system` as a tenant namespace and bind the privileged workload role there | **In progress on this branch.** Residual against the `6de903b2` RBAC scoping |
| High | DNS rebinding: validated addresses were discarded and the driver re-resolved the hostname before connecting. The SSH bastion host is not validated at all | **In progress on this branch.** Residual against SP-SEC-010 |
| High | T-SQL four-part linked-server names bypassed governance; DuckDB ran with `enable_external_access=true` | **Fixed.** These were the two strict xfails deliberately left recorded by `432b6dfe` |
| High | Multipart upload quota is neither atomic nor shared across workers, so concurrent or multi-replica uploads can exceed it | **In progress on this branch.** Residual against SP-SEC-007 |
| Medium | Notebook proxy authorized on user id only, ignoring the active organization | **Fixed** |
| Medium | TLS-key migration is optional, so legacy plaintext rows persist until an operator runs it | **Open by design.** Residual against SP-SEC-014; see prerequisites |
| Dependency | Web lockfile criticals via `compassql` → `datalib` → `request` → `form-data`, plus a DOMPurify `CUSTOM_ELEMENT_HANDLING` advisory | **Fixed** |
| Critical (new) | The app's DOMPurify `attributeNameCheck` regex admitted `on*` handlers on allowed custom elements, so `<sp-x onclick=...>` in notebook output survived sanitization — a live XSS in the notebook output path | **Fixed** (blocked). Contradicts the first-round "chart HTML is passed through DOMPurify" positive control |

### Accepted residual: Clerk JWTs are not bound to this application

`CLERK_JWT_AUDIENCE` and `SP_EXPECTED_AZP` are both unset, so a token issued for
any application on the same Clerk instance is accepted. A startup requirement for
one of them was implemented and then **removed at the maintainers' direction**:
both had been tried previously and did not work with this Clerk configuration.
The instance has no JWT templates, and its default session token carries neither
`aud` nor `azp`, so enforcing either would have refused every request.

The verification code remains in place and activates automatically if either
variable is ever set — no further change is needed to adopt binding once a
working Clerk template exists.

Residual risk is bounded by how many applications share the Clerk instance: with
a single application it is negligible, and it grows with each additional one.
Revisit if another application is added to the same instance.

## Deployment prerequisites

Several fixes fail closed. An operator must satisfy all of the following before
or during rollout, or the corresponding surface breaks rather than degrades.

- **`SP_GATEWAY_RUNTIME_GROUPS` must be set before the gateway restarts.**
  Without it every pod and Secret write returns 403 under the new
  namespace-scoped RBAC.
- **Kubernetes `roleRef` migration.** `roleRef` is immutable, so existing
  per-namespace RoleBindings must be deleted and recreated.
  `migrate-sp-sec-009.sh` does this; it is dry-run by default and has `--verify`
  and `--rollback`. The Kyverno webhook-exclusion decision and the EKS
  access-entry mapping remain per-cluster manual steps.
- **`SP_GITHUB_APP_CLIENT_SECRET` in cloud mode**, and GitHub's *Request user
  authorization (OAuth) during installation* toggle enabled on the App. The
  callback now completes the user-authorization leg; without both, installs
  fail. Cloud readiness fails fast rather than failing per callback.
- **`SP_SANDBOX_MANAGER_URL` is now security-relevant.** It defines which
  endpoint is trusted with the platform sandbox token. It is no longer just a
  routing setting.
- **`SP_GITHUB_WEBHOOK_SECRET`.** The GitHub bot webhook route is disabled in
  every mode unless a secret is configured.
- **No Clerk JWT template is required.** Application binding is an accepted
  residual (see above); nothing about `aud`/`azp` blocks a deploy.
- **TLS migration for legacy rows.** The dry-run-by-default helper must be run
  to move pre-existing plaintext TLS client keys into encrypted extras. Nothing
  runs it automatically.

## Verification

What was actually exercised:

- **Real cloud-mode E2E authorization matrix** (`c42fb154`): two live uvicorn
  gateways in `SP_DEPLOYMENT_MODE=cloud` against throwaway Postgres databases,
  no `TestClient`, no dependency overrides, no monkeypatched `jwt.decode`. One
  verifies genuinely Clerk-signed tokens through Clerk's real JWKS; the other
  uses a local JWKS server for the negatives Clerk will not mint. 635 tests, with
  the route matrix discovered from the app's own dependency tree so a route that
  loses its guard fails the suite rather than dropping out of it. The
  credential-export assertion seeds a real password and asserts the canary is
  absent from every non-admin response.
- **A real-browser CSRF suite** (`9fff7883`): Playwright driving Chromium
  against a cloud-mode gateway with a genuine Clerk session injected as
  `__session`, and an attacker origin on a separate host so the browser itself
  sets `Origin` and `Sec-Fetch-Site: cross-site`. This covers the cookie path
  Bearer-based tests cannot reach.
- **Live SQL governance** (`432b6dfe`): 454 tests including real SQL Server and
  Postgres containers, proving the cap is enforced end to end and that each
  previously-allowed bypass is blocked. DuckDB external access exercised in the
  second round.
- **A real kind cluster (k8s 1.34)** for admission (`6de903b2`), which compiles
  the CEL and runs the full admission chain: 52 rule assertions and 18
  `kubectl auth can-i` checks, with a pre-migration baseline confirming the
  legacy grant was genuinely exploitable.
- **Live pre-fix reproduction** for the unauthenticated gateway listener, the
  unauthenticated notebook `dbt` execution and scaffold write, and the MSSQL
  `OPENROWSET` class of bypasses.
- **Nine tests against real GitHub** (`0cad4df5`), including one proving GitHub
  itself rejects a scoped mint for an inaccessible repository with 422.

What was **not** verified:

- **Cross-org isolation is only partially covered.** The two-tenant assertions
  are targeted (BYOK provider custody, pool identity, GitHub installation
  binding). There is no systematic cross-tenant matrix over the full route set,
  and the eval-runner cross-tenant state is still open.
- **Real AWS KMS custody was not exercised.** The BYOK tests assert that each
  org's own provider is used and that the operator provider records zero calls;
  they do not perform a genuine KMS wrap/unwrap against AWS.
- **The Kubernetes notebook-token path was not run end to end.** The per-session
  token, Secret, initContainer and tmpfs staging were verified against a
  token-enabled server and in manifest tests, not on a live cluster.
- **Browser coverage is Chromium only.** No Firefox or WebKit run, so
  browser-specific `Sec-Fetch-*` and cookie behaviour outside Chromium is
  unverified.
- Production-cluster rollout of the RBAC migration, the Clerk JWT template, and
  the TLS row migration are all untested against a real deployment.

## Automated scan status

The GitHub security run recorded for the original revision is
[`30467023500`](https://github.com/SignalPilot-Labs/SignalPilot/actions/runs/30467023500):
TruffleHog and Semgrep passed; Python dependency audit, Node dependency audit,
Bandit and the aggregate gate failed. `011114a5` addresses all four failing jobs
and the second-round dependency pass addresses the remaining web-lock criticals,
but the workflow has not been re-run to green on `e77641af`. See
[automated-results.md](automated-results.md) for the per-package detail behind
the original run.

## Reports

- [Backend, MCP, and infrastructure audit](backend-audit.md)
- [Frontend and browser audit](frontend-audit.md)
- [Secrets and private-document audit](secrets-and-private-docs.md)
- [Automated scan results](automated-results.md)
- [Whole-app runtime audit + Round 2 net-new surfaces](app-runtime-audit-2026-07-29.md)

## Caveat on these reports

These reports are themselves exactly the class of tracked internal document that
[secrets-and-private-docs.md](secrets-and-private-docs.md) flags as a
confidentiality risk (SP-SEC-022). They reference customer names, private
repository paths and open weaknesses. Four of the six files were already
tracked; the runtime audit and the automated results are new and add to that
exposure. They were committed in an isolated commit (`4db8cac0`) so it can be
dropped on its own. Removing them, and the `writeups/` documents, from the
repository and its reachable history remains a separate repository-governance
decision that this branch does not attempt.

## Retest criteria

Close the audit only when the second-round Criticals and Highs are landed, the
security workflow passes on the resulting commit with no unaccepted high or
critical dependency findings, the deployment prerequisites above are satisfied
in the target environment, and a cross-tenant isolation test covers the eval
runner and the sandbox/notebook paths.
