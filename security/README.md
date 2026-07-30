# SignalPilot Security Audit

Audit date: 2026-07-29

Audited revision: `52c26a8f` on local branch `feature-sprint-7-22`

Scope: application code, MCP surfaces, deployment configuration, browser code,
locked dependencies, CI security controls, and tracked sensitive material. Existing
uncommitted work was preserved and was not included in the reproducible GitHub CI
run.

This is a source review and configuration audit. It is not a penetration test of a
deployed environment.

## Executive summary

The current revision should not be promoted as-is. Cloud authorization confuses API
scopes with organization roles, allowing ordinary authenticated users to pass
`admin` scope gates and allowing non-admin API keys to pass organization-admin
dependencies. The default Docker Compose deployment also exposes the gateway on
every host interface while local mode permits requests without an API key.

The highest-priority findings are:

1. **Critical - cloud admin scope gates do not enforce an organization role.**
   Clerk/JWT users have no middleware `auth` object, and the scope guard grants that
   state every scope. Conversely, every API key is treated as an organization admin
   regardless of its scopes.
2. **Critical - a basic cloud member can export database credentials.** The export
   route relies on the ineffective `admin` scope check before returning decrypted
   connection strings and TLS material.
3. **Critical - `compare_join_types` bypasses governed SQL validation.** Agent-supplied
   join and predicate fragments are interpolated into SQL and sent directly to a
   connector; the helper named `_validate_sql` checks only non-emptiness and length.
4. **Critical - the GitHub callback can mint another tenant's installation token.**
   A valid state binds the destination organization, but the caller-supplied
   installation ID is never proven to belong to that organization.
5. **Critical - unauthenticated gateway exposed by the default compose stack.**
   `docker-compose.yml` publishes `3300:3300`, while local authentication accepts a
   missing API key and grants the resulting principal every scope.
6. **Critical - tenant users can configure arbitrary eval container workloads.**
   The eval routes use the ineffective admin gate, share global configuration and
   transcripts, and execute repository-controlled images and scripts through the
   host Docker API.
7. **High - S3 multipart uploads can bypass the configured size quota.** A client
   chooses the claimed object size, but the presigned part URLs do not bind the
   actual part length. Oversized or abandoned parts can consume storage and transfer
   before the final object-size check.
8. **High - SQL governance fails open for several dialects and limits.** Dangerous
   MSSQL and DuckDB external-access forms pass validation, while `LIMIT ALL` and
   `FETCH FIRST` variants remain unbounded.
9. **High - the locked MCP SDK has three published advisories.** The gateway uses a
   stateful Streamable HTTP MCP app, so the session-ownership advisory is relevant to
   its authenticated deployment.
10. **High - Kubernetes runtime credentials are cluster-wide.** The EC2 runtime group
   can read Secrets, exec into pods, and manage pods across all namespaces.
11. **High - locked JavaScript dependencies contain blocking vulnerabilities.** The
   web lock contains 2 critical and 6 high advisories; the docs lock contains 1
   critical and 6 high advisories. Some critical transitive packages have temporary
   risk exceptions, but the CI gate still reports unaccepted high findings.
12. **Critical - the notebook-server `dbt` router is entirely unauthenticated.**
   All 9 handlers in `notebook-server/.../endpoints/dbt.py` lack the `@requires`
   decorator every sibling router uses; the auth backend annotates but does not
   reject. `POST /api/dbt/command` runs dbt (an arbitrary-code engine) against an
   attacker-chosen project, and `POST /api/dbt/clone_project` passes an
   unconstrained `git_url`/`target_dir` to `git clone` (RCE via `ext::`, SSRF,
   arbitrary file write). See [app-runtime-audit](app-runtime-audit-2026-07-29.md)
   §Round 2 R2-1. The `agent` router (R2-2) is likewise ungated.

## Disposition

| Priority | Required action |
|---|---|
| P0 | Separate organization roles from API scopes. Require `OrgAdmin` or a staff role on every administrative route and derive API-key role from explicit admin scope. |
| P0 | Add `OrgAdmin` to credential export and clone routes. Bind GitHub installation IDs to the authenticated installer and organization before minting a token. |
| P0 | Route every constructed MCP query through `validate_sql` and `inject_limit`; parse join and predicate fragments rather than interpolating free text. |
| P0 | Bind the gateway to loopback in local compose or require a generated local API key. Do not allow `local_nokey` on a non-loopback listener. |
| P0 | Make eval configuration and run state organization-scoped, restrict the feature to staff, and isolate execution from the gateway process and Docker socket. |
| P0 | Upgrade `mcp` to at least `1.28.1` in every Python lock and rebuild images. |
| P0 | Replace the cluster-wide Kubernetes runtime binding with namespace-scoped authorization. |
| P0 | Add `@requires("edit")` to every notebook-server `dbt` and `agent` handler; enforce the `DBT_COMMANDS` allowlist; confine dbt project/target dirs to a workspace root; reject non-http(s) git schemes in `clone_git_repo`. |
| P1 | Fail closed on SSRF validation, deny dangerous operations for every supported SQL dialect, disable DuckDB external access, and enforce a post-execution row cap. |
| P1 | Validate the BYOS `SandboxClient` base_url through the SSRF denylist (leaks `SP_SANDBOX_TOKEN` otherwise); reject absolute passthrough URLs in analysis-delivery snapshot fetching; confine `/api/files/browse` to an allowed root. |
| P1 | Make multipart quotas server-owned and enforce exact part sizes, ownership, concurrent-byte quotas, short expiry, and automatic abort. |
| P1 | Instantiate the configured provider for each tenant BYOK key and encrypt TLS client private keys outside connection metadata. |
| P1 | Resolve the blocking npm advisories and make the security workflow pass. |
| P1 | Review whether the tracked internal planning, customer, vendor, and legal documents are permitted in the repository and its remote history. |
| P2 | Require authentication for notebook API-key mutation and local GitHub webhooks; tighten CSP and other browser hardening controls. |

## Reports

- [Backend, MCP, and infrastructure audit](backend-audit.md)
- [Frontend and browser audit](frontend-audit.md)
- [Secrets and private-document audit](secrets-and-private-docs.md)
- [Automated scan results](automated-results.md)
- [Whole-app runtime audit + Round 2 net-new surfaces](app-runtime-audit-2026-07-29.md)

## Verification status

The GitHub security run for this revision is
[`30467023500`](https://github.com/SignalPilot-Labs/SignalPilot/actions/runs/30467023500).
TruffleHog and Semgrep passed. Python dependency audit, Node dependency audit,
Bandit, and the aggregate security gate failed. See
[automated-results.md](automated-results.md) for the exact package and rule results.

## Retest criteria

Close the audit only after all P0 and P1 actions are implemented, the security
workflow passes on the resulting commit, dependency scans report no unaccepted high
or critical findings, and deployment tests demonstrate that an unauthenticated
non-loopback client cannot reach gateway APIs or MCP tools.
