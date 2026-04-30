# SignalPilot Security Audit

**Audit date:** 2026-04-30
**Repo branch:** `autofyn/i-need-you-to-ge-30a2b9`
**Audited surface:** `signalpilot.ai` (cloud), `gateway.signalpilot.ai` (hosted gateway), hosted sandbox service.

---

## How to read this audit

Start with [`issues.md`](issues.md). It contains the executive summary table listing all 58 findings sorted by severity, a one-sentence description of each, the affected file(s), and a link to the detailed proposal.

Each `{slug}-proposal.md` contains: a plain-language problem description with exact file and line citations, an attacker-centric exploit scenario, the exact code change needed (design-level sketch, not full implementation), and a verification/test plan the team can run to confirm the fix.

Severity is graded against the **hosted multi-tenant cloud deployment**. Behavior that only affects local/Docker-compose setups is noted explicitly and demoted to Low or Info unless it has a realistic cloud impact path.

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

**Out of scope (explicit):**
- Binary review of the `runsc` (gVisor) runtime itself
- Third-party JavaScript supply chain beyond `package-lock.json` lockfile inspection
- SOC 2 controls, organizational policies, or pen-test of the live cloud environment
- Stripe/billing webhook implementation (flagged as finding #52 for follow-up)
- AWS/GCP/Azure account-level IAM configuration not in this repo
- Infra-as-code (Terraform, Pulumi, etc.) — not present in repo

---

## Methodology

Static code review of the repository at the branch listed above. Every file named in the findings list was read directly. Line numbers were verified by reading the source at review time.

No dynamic testing was performed. Exploit scenarios are constructed from reading the code; they have not been verified against a live deployment.

Confidence levels in each proposal reflect how certain the reviewer is that the finding is exploitable as described, not the severity of the impact.
