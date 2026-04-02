---
description: "Use when actively scanning for new security vulnerabilities, performing threat modeling, or auditing code for OWASP Top 10 issues. Discovers new findings with confidence-rated reporting. Complements /security-audit which covers remediation of known findings."
---

# Security Scan

Systematic vulnerability discovery for the SignalPilot codebase. This skill finds
new security issues — use `/security-audit` to remediate known ones.

## Iron Law

**Concrete exploit scenarios required.** "This pattern is insecure" alone does not
qualify as a finding. Every reported issue must include a realistic attack vector
demonstrating how an attacker could exploit it.

## Scanning Phases

Run phases in order. Skip phases that don't apply to changed files (diff-aware mode).

**Diff-aware mode:** On a feature branch, scope scanning to changed files:
```bash
CHANGED=$(git diff origin/main --name-only 2>/dev/null)
if [ -n "$CHANGED" ]; then
  echo "DIFF-AWARE: Scanning $(echo "$CHANGED" | wc -l) changed files"
  # Only run phases relevant to changed file types
  echo "$CHANGED" | grep -q '\.py$' && echo "RUN: Phase 4-6 (Python)"
  echo "$CHANGED" | grep -qE 'gateway/(engine|governance)' && echo "RUN: Phase 5 (SQL Safety)"
fi
```
For full-codebase scans, run on main or pass `--full`.

### Phase 1 — Architecture & Attack Surface

```bash
# Map exposed endpoints
grep -rn "@app\.\(get\|post\|put\|delete\|patch\)" --include="*.py" /workspace
# Map WebSocket handlers
grep -rn "websocket" --include="*.py" /workspace
# Map external integrations
grep -rn "requests\.\|httpx\.\|aiohttp\." --include="*.py" /workspace
```

Catalog: public endpoints, auth-gated vs open, external API calls, data flows
between services.

### Phase 2 — Secrets Archaeology

```bash
# Check git history for leaked secrets
git log --all -p --diff-filter=D -S "password\|secret\|api_key\|token" -- "*.py" "*.env" "*.json" "*.yml" | head -200
# Check current files for hardcoded credentials
grep -rn "password\s*=\s*[\"']" --include="*.py" /workspace
grep -rn "SECRET_KEY\|API_KEY\|PRIVATE_KEY" --include="*.py" --include="*.env" /workspace
# Check for .env files in repo
find /workspace -name ".env*" -not -path "*/node_modules/*" -not -path "*/.git/*"
```

### Phase 3 — Dependency Supply Chain

```bash
# Python dependencies with known vulnerabilities
pip audit 2>/dev/null || echo "pip-audit not installed"
# Check for pinned vs unpinned dependencies
cat /workspace/*/requirements*.txt /workspace/*/pyproject.toml 2>/dev/null | grep -v "^#"
# Node dependencies
cd /workspace && find . -name "package.json" -not -path "*/node_modules/*" -exec dirname {} \; | head -5
```

### Phase 4 — Authentication & Authorization

Review auth middleware, session handling, API key validation:
- Are all sensitive endpoints gated?
- Is auth checked before business logic?
- Are API keys compared with constant-time comparison?
- Is session token storage secure (httpOnly, secure, sameSite)?

### Phase 5 — SQL Injection & Query Safety

SignalPilot-specific: the gateway executes user-provided SQL.
- Is `validate_sql()` called before every execution path?
- Can the sqlglot fallback be bypassed?
- Are `_BLOCKED_STATEMENT_TYPES` comprehensive?
- Is `_quote_identifier()` used for all dynamic identifiers?
- Can LIMIT injection be circumvented?

### Phase 6 — OWASP Top 10 Sweep

Check for each category with codebase-specific patterns:

| OWASP Category | What to look for |
|---|---|
| A01 Broken Access Control | Endpoints missing auth, IDOR via predictable IDs |
| A02 Cryptographic Failures | Weak hashing, missing encryption at rest, plaintext secrets |
| A03 Injection | SQL injection, command injection via subprocess, template injection |
| A04 Insecure Design | Missing rate limiting, no account lockout, excessive data exposure |
| A05 Security Misconfiguration | CORS wildcard, debug mode in prod, default credentials |
| A06 Vulnerable Components | Outdated dependencies with known CVEs |
| A07 Auth Failures | Weak password policies, missing MFA, session fixation |
| A08 Data Integrity Failures | Unsigned updates, missing integrity checks on external data |
| A09 Logging Failures | Sensitive data in logs, missing audit trail for auth events |
| A10 SSRF | Unvalidated URLs passed to HTTP clients, internal network access |

### Phase 7 — STRIDE Threat Model

For each major component (gateway, connectors, sandbox, web UI), assess:

- **S**poofing — Can an attacker impersonate a user or service?
- **T**ampering — Can requests/data be modified in transit?
- **R**epudiation — Can actions be performed without audit trail?
- **I**nformation Disclosure — Can sensitive data leak via errors, logs, or side channels?
- **D**enial of Service — Can a single request exhaust resources?
- **E**levation of Privilege — Can a user escalate to admin or access other tenants?

## Finding Format

Every finding MUST use this format:

```
### [SEVERITY] Title
**Confidence:** N/10
**Location:** file:line
**Category:** OWASP-AXX or STRIDE-X

**Exploit scenario:**
1. Attacker does X
2. This causes Y
3. Result: Z (data leak / auth bypass / RCE / etc.)

**Evidence:**
<code snippet showing the vulnerability>

**Recommendation:**
<specific fix with code example>
```

## Confidence Thresholds

- **8-10:** Report as confirmed finding. Include in summary.
- **5-7:** Report as TENTATIVE. Flag for investigation but don't count in score.
- **1-4:** Do not report. Too speculative.

## False Positive Exclusions

Do NOT report these as findings:
1. DoS via large input (unless single request causes OOM)
2. Missing rate limiting on read-only endpoints
3. Test-only code or test fixtures
4. UUIDs as identifiers (unguessable by design)
5. React JSX output (escaped by default)
6. Environment variables as secret storage (standard practice)
7. CORS configuration for localhost in development
8. Missing CSP headers on API-only services
9. Theoretical timing attacks without measured evidence
10. "Best practice" gaps with no concrete exploit path
11. Missing HTTPS (infrastructure concern, not application)
12. Generic error messages that don't leak implementation details
13. Dependencies with CVEs that don't apply to our usage
14. Missing security headers on non-browser endpoints
15. Logging of non-sensitive request metadata

## Output

Produce a **Security Scan Report** with:

1. **Scan scope** — files/components reviewed, diff-aware or full
2. **Confirmed findings** (confidence 8+) — sorted by severity
3. **Tentative findings** (confidence 5-7) — for investigation
4. **Attack surface summary** — endpoints, auth coverage, external integrations
5. **STRIDE assessment** — one-line status per component per threat category
6. **Recommendation priority** — ordered remediation roadmap

## Disclaimer

This scan is not a substitute for professional penetration testing. LLMs can miss
subtle vulnerabilities and produce false negatives. For systems handling PII,
payments, or credentials, professional security audit is essential.
