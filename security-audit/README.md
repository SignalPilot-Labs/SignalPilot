# SignalPilot Security Audit

**Audit date:** 2026-04-30 (round 1) / verified + extended 2026-04-30 (round 2)
**Repo branch:** `autofyn/i-need-you-to-ge-30a2b9`
**Audited surface:** `signalpilot.ai` (cloud), `gateway.signalpilot.ai` (hosted gateway), hosted sandbox service.

---

## How to read this audit

Start with [`issues.md`](issues.md). It contains the executive summary table listing all 68 findings sorted by severity, a one-sentence description of each, the affected file(s), the round-2 verification status, and a link to the detailed proposal.

Each `{slug}-proposal.md` contains: a plain-language problem description with exact file and line citations, an attacker-centric exploit scenario, the exact code change needed (design-level sketch, not full implementation), and a verification/test plan the team can run to confirm the fix.

Severity is graded against the **hosted multi-tenant cloud deployment**. Behavior that only affects local/Docker-compose setups is noted explicitly and demoted to Low or Info unless it has a realistic cloud impact path.

---

## Round 2 deltas

Round 2 (re-)verified every round-1 finding against current source and added 10 new findings. See `/tmp/round-2/audit-verification.md` for the per-finding verification log.

- **55** of round 1's findings are still **VALID** as written.
- **1** finding (#44 request-correlation-header-not-validated) is **STALE** — the original log-injection vector is closed by `_REQUEST_ID_PATTERN` validation; severity demoted from Low to Info.
- **1** finding (#56 mcp execute_code tool in cloud) is **FIXED** in current source — tool registration now wrapped in `if not _is_cloud:`.
- **10 new findings** added (#59-#68): git-clone arg injection, dbt Cloud SSRF, MCP XFF spoofing, sandbox container caps, audit-export memory cap, billing open-redirect, MCP-mount-at-root fall-through, shared-volume key leak, OPTIONS-bypasses-middlewares, and `last_used_at` admin leakage / write amplification.

---

## Severity legend

| Severity | Meaning |
|----------|---------|
| **Critical** | Exploitable by an unauthenticated remote attacker; leads to complete multi-tenant data compromise, RCE, or authentication bypass with no preconditions. CVSS >= 9.0 analog. |
| **High** | Exploitable by an authenticated user or requires one precondition; cross-tenant data access, significant privilege escalation, or security control bypass. CVSS 7.0-8.9 analog. |
| **Medium** | Exploitable under realistic conditions; meaningful impact such as partial data leakage, degraded security posture, or a building block for a larger attack. CVSS 4.0-6.9 analog. |
| **Low** | Requires multiple unlikely preconditions or has limited impact in isolation; defense-in-depth improvement. CVSS 1.0-3.9 analog. |
| **Info** | No direct exploitability; design note, missing documentation, or a stub that must be hardened before the feature ships. CVSS 0 analog. |

---

## Scope

**In scope:**
- `signalpilot/gateway/gateway/` — Python FastAPI gateway
- `signalpilot/web/` — Next.js frontend (Clerk auth, API routes, middleware)
- `sp-sandbox/` — gVisor sandbox manager
- `Dockerfile.gateway`, `Dockerfile.sandbox`, `Dockerfile.web`, `docker-compose.yml`
- Cloud-mode configuration and multi-tenant isolation

**Deprioritized (2026-04-30):** The owner has disabled the sandbox feature (sandbox containers, `/execute`, sandbox UI, MCP `execute_code`, host-data mounts, shared-volume key plumbing) and the project / project-import feature (git-clone project creation, dbt Cloud project discovery, dbt `profiles.yml` materialization) in the cloud deployment and is not actively maintaining them. Findings touching those features remain in the audit at their original severity, but should be treated as low priority until the features are re-enabled. See the "Deprioritized scope (2026-04-30)" section in [`issues.md`](issues.md) for the full ID list.

**Out of scope (explicit):**
- Binary review of the `runsc` (gVisor) runtime itself
- Third-party JavaScript supply chain beyond `package-lock.json` lockfile inspection
- SOC 2 controls, organizational policies, or pen-test of the live cloud environment
- Stripe/billing webhook implementation (flagged as findings #52 and #64 for follow-up)
- AWS/GCP/Azure account-level IAM configuration not in this repo
- Infra-as-code (Terraform, Pulumi, etc.) — not present in repo

---

## Methodology

Static code review of the repository at the branch listed above. Every file named in the findings list was read directly. Line numbers were verified by reading the source at review time. Round 2 re-read the cited regions for every prior finding and added new file reads (notably `project_store.py`, `api/projects.py`, `correlation.py`, `mcp_server.py`).

No dynamic testing was performed. Exploit scenarios are constructed from reading the code; they have not been verified against a live deployment.

Confidence levels in each proposal reflect how certain the reviewer is that the finding is exploitable as described, not the severity of the impact.
