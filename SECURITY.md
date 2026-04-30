# Security Policy

## Supported Versions

Security fixes land on `main`. We recommend running the latest commit from `main` or the most recent tagged release.

## Reporting a Vulnerability

If you believe you've found a security vulnerability in SignalPilot, please report it privately — do **not** open a public GitHub issue.

Email: **security@signalpilot.ai**

Please include:

- A description of the issue and its potential impact
- Steps to reproduce (proof-of-concept code or commands if available)
- The affected version, commit SHA, or deployment configuration
- Whether the issue is already public or coordinated with another party

## What to Expect

- **Acknowledgement** within 3 business days of your report.
- **Triage and initial assessment** within 7 business days.
- **Coordinated disclosure** — we'll work with you on a fix timeline and credit you in the advisory if you'd like.

We use [GitHub Security Advisories](https://github.com/SignalPilot-Labs/signalpilot/security/advisories) to publish fixed vulnerabilities once a patch is available.

## Scope

In scope:

- The SignalPilot gateway (FastAPI backend, MCP server, REST API)
- The web UI (Next.js frontend)
- The Claude Code plugin
- The gVisor sandbox (`sp-sandbox/`)
- Database connectors and credential storage

Out of scope:

- Vulnerabilities in third-party dependencies (please report upstream; we'll bump the dependency)
- Issues that require a malicious admin user with full write access
- Denial-of-service via misconfiguration (unbounded queries, etc. — these are expected to be governed via the deployment configuration)

Thanks for helping keep SignalPilot and its users safe.
