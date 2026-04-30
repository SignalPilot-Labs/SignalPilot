# `package.json` has empty `overrides`, no documented `npm audit` gate

- Slug: package-lock-no-overrides-and-no-audit-step-in-ci
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/web/package.json:36`

Back to [issues.md](issues.md)

---

## Problem

The `package.json` has an empty `overrides` field:

```json
// package.json:36 (approximate)
{
  "overrides": {}
}
```

There is no `npm audit` step in any CI/CD pipeline visible in the repo (no `.github/workflows/` found — see finding [ci-not-in-repo-cannot-audit](ci-not-in-repo-cannot-audit-proposal.md)). Without a CI npm audit gate:

1. **Vulnerable transitive dependencies can ship.** The `node_modules` dependency tree includes hundreds of transitive packages. Any of them may have known CVEs that go undetected until a breach or external report.
2. **No automatic vulnerability alerting.** Without Dependabot or equivalent, new CVEs in existing dependencies are not surfaced.
3. **Empty `overrides` signals planned but unimplemented mitigation.** The `overrides` field is typically used to force a specific version of a transitive dependency to resolve a CVE. An empty field suggests the team is aware of this mechanism but has not needed it yet — or has forgotten to clean up a placeholder.

---

## Impact

- Undetected vulnerable transitive dependency ships to production.
- For a Next.js app with Clerk, the most likely high-severity transitive CVEs would be in `next`, `react`, or authentication libraries.
- Low current risk (package-lock.json is present, so versions are pinned), but no process to detect future vulnerabilities.

---

## Exploit scenario

1. A CVE is published for a transitive dependency (e.g., `cookie@<0.7.0` — ReDoS or prototype pollution).
2. `package-lock.json` still pins the vulnerable version.
3. Without a CI audit step or Dependabot, the vulnerability goes undetected.
4. An attacker exploits the vulnerability in the production app (e.g., via a crafted cookie that triggers prototype pollution, leading to RCE in the Next.js SSR context).

---

## Affected surface

- Files: `signalpilot/web/package.json:36`, `package-lock.json`
- Endpoints: All Next.js endpoints (server-side dependencies)
- Auth modes: Cloud and local

---

## Proposed fix

1. **Add `npm audit` to CI:**

```yaml
# .github/workflows/security.yml:
- name: npm audit
  run: npm audit --audit-level=high
  working-directory: signalpilot/web
```

2. **Enable Dependabot:**

```yaml
# .github/dependabot.yml:
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/signalpilot/web"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
  - package-ecosystem: "pip"
    directory: "/signalpilot/gateway"
    schedule:
      interval: "weekly"
```

3. **Remove or populate the empty `overrides` field:**

```json
// package.json — remove empty field or document its purpose:
// Remove: "overrides": {}
// Or use: "overrides": { "vulnerable-pkg": "^safe-version" }
```

4. **Pin major versions for critical dependencies:**

```json
// package.json:
"next": "~15.3.0",  // Pin to minor version, allow patches only
"@clerk/nextjs": "~6.1.0"
```

---

## Verification / test plan

**CI gate:**
```bash
npm audit --audit-level=high
# Should return 0 (no high/critical vulnerabilities) or fail the build
```

**Dependabot:**
- Enable Dependabot, verify it creates PRs for dependency updates within 24h of a CVE publication.

---

## Rollout / migration notes

- Run `npm audit` immediately to assess current state. If vulnerabilities exist, address them before enforcing the CI gate.
- Use `npm audit --audit-level=high` to avoid failing on low/moderate findings initially, then tighten to `--audit-level=moderate` over time.
- Rollback: remove the CI audit step (not recommended).
