# Security CI Controls

This repository uses `.github/workflows/security.yml` to provide PR evidence for:

- CC7: dependency vulnerability scanning, secret scanning, and SAST on every pull request and `main` push.
- CC8: a single `security-gate` status check that can be required before merging to `main`.

Initial dependency-scan enforcement:

- Blocking: gateway Python dependencies, sandbox Python dependencies.
- Informational until dependency remediation lands: notebook-server Python dependencies and npm dependencies.

The informational scans are still run on every pull request and `main` push. Promote them to blocking after the existing high/critical npm findings are fixed and `signalpilot/notebook-server/uv.lock` can be updated without the missing local `sp_docs` source.

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
