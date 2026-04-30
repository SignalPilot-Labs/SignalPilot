# No `.github/workflows/` in repo at root scan; cannot verify secret handling, branch protection, OIDC for deploy

- Slug: ci-not-in-repo-cannot-audit
- Severity: Info
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: repo root (absence of `.github/workflows/`)

Back to [issues.md](issues.md)

---

## Problem

No `.github/workflows/` directory was found in the repository. This means:

1. **CI/CD security cannot be audited.** The audit cannot verify:
   - Secret handling (are secrets scoped to only the jobs that need them?).
   - Branch protection rules (is `main` protected with required reviews?).
   - OIDC-based deployments (are AWS/GCP credentials injected via OIDC instead of long-lived secrets?).
   - Pin status of third-party GitHub Actions (unpinned actions are a supply-chain risk).
   - Artifact signing and SLSA provenance.
2. **No npm audit or pip audit in CI** (see [package-lock-no-overrides-and-no-audit-step-in-ci](package-lock-no-overrides-and-no-audit-step-in-ci-proposal.md)).
3. **No automated security scanning** (SAST, secret scanning, container scanning).
4. **No dependency vulnerability alerts** without Dependabot configuration.

The CI/CD pipeline is a critical security boundary. A compromised CI job with access to production secrets can silently modify deployments, exfiltrate credentials, or backdoor the application.

---

## Impact

- Cannot verify current CI/CD security posture.
- CI/CD pipelines outside this repo may have misconfigured secrets, overly permissive roles, or unpinned third-party actions.
- No automated dependency vulnerability detection.

---

## Recommended actions

This is an audit flag, not a code finding. The team should:

1. **Document where CI/CD pipelines live** (separate repo, external CI service, etc.).
2. **Share CI/CD config with security review** to audit secret scoping, action pinning, and OIDC setup.
3. **Add Dependabot configuration** to this repo (see [package-lock-no-overrides-and-no-audit-step-in-ci](package-lock-no-overrides-and-no-audit-step-in-ci-proposal.md)).
4. **Document branch protection rules** for the SignalPilot repos.

---

## Proposed fix (if creating CI/CD in this repo)

```yaml
# .github/workflows/security.yml:
name: Security Checks
on:
  push:
    branches: [main, autofyn/*]
  pull_request:

jobs:
  npm-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4  # Pin to SHA in production
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm ci
        working-directory: signalpilot/web
      - run: npm audit --audit-level=high
        working-directory: signalpilot/web

  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pip-audit
      - run: pip-audit --requirement requirements.lock
        working-directory: signalpilot/gateway

  container-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build gateway image
        run: docker build -f Dockerfile.gateway -t signalpilot-gateway .
      - name: Scan with Trivy
        uses: aquasecurity/trivy-action@master  # Pin to SHA in production
        with:
          image-ref: signalpilot-gateway
          severity: HIGH,CRITICAL
          exit-code: 1
```

---

## Verification / test plan

**Follow-up questions for the team:**
1. Where are CI/CD pipeline definitions stored?
2. Are production secrets injected via OIDC or stored as static GitHub Secrets?
3. Are third-party GitHub Actions pinned to commit SHAs?
4. What branch protection rules are in place for `main`?

---

## Rollout / migration notes

- No immediate code changes required.
- This finding flags a gap in the audit scope.
- Add Dependabot configuration as the first concrete action (`security-audit/` deliverable + [package-lock-no-overrides-and-no-audit-step-in-ci](package-lock-no-overrides-and-no-audit-step-in-ci-proposal.md)).
