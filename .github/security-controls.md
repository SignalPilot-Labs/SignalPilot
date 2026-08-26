# Security CI Controls

This repository uses `.github/workflows/security.yml` to provide PR evidence for:

- CC7: dependency vulnerability scanning, secret scanning, and SAST on every pull request and `main` push.
- CC8: a single `security-gate` status check that can be required before merging to `main`.

Dependency-scan enforcement:

- Blocking: gateway Python dependencies, notebook-server Python dependencies, sandbox Python dependencies, web npm dependencies, and docs npm dependencies.
- Python scans export each `uv.lock` to a temporary requirements file and run `pip-audit`.
- Node scans run a high/critical npm audit gate in both npm projects. Moderate and low advisories should be tracked through Dependabot or risk-accepted with a remediation SLA.
- The web audit gate currently risk-accepts `request` and `form-data` findings that enter only through `compassql -> datalib`. The data explorer imports CompassQL schema/recommendation helpers in the browser and does not call datalib's network loading path. Review this exception by 2026-09-30 and replace CompassQL or its data-explorer usage to remove it.

Initial SAST enforcement:

- Semgrep uses the PR base commit or previous push commit as its baseline, so new findings fail without blocking on inherited findings.
- Bandit uses `.github/bandit-baseline.json` for the same reason. Refresh the baseline only after triaging or fixing the existing findings.

Required branch rule for `main`:

- Require a pull request before merging.
- Require at least 1 approving review.
- Dismiss stale approvals when new commits are pushed.
- Require status checks to pass before merging.
- Require the `security-gate` status check.
- Do not allow bypasses except explicit break-glass administrators.

Apply the rule after `security.yml` has landed on `main`, so GitHub can see the `security-gate` check name.
