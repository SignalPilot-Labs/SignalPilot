# `enterprise-connections.md:36` references `endless-fly-19.clerk.accounts.dev` dev hostname — may be hardcoded somewhere

- Slug: clerk-research-mentions-dev-keys-endless-fly-19
- Severity: Info
- Cloud impact: Partial
- Confidence: Low
- Affected files / endpoints: `signalpilot/web/enterprise-connections.md:36` (docs only — confirm by grep)

Back to [issues.md](issues.md)

---

## Problem

The `enterprise-connections.md` document references `endless-fly-19.clerk.accounts.dev` — a Clerk development tenant identifier. This appears to be the development Clerk tenant used during implementation of the Clerk enterprise SSO research.

Concerns:
1. **The dev hostname may be hardcoded elsewhere.** If `endless-fly-19.clerk.accounts.dev` or the corresponding publishable key (`pk_test_...`) appears in application source code (not just docs), it would be a hardcoded dev credential in production code.
2. **The dev tenant should be rotated.** Sharing a dev tenant identifier in a public (or semi-public) document means anyone who finds this document knows the Clerk tenant and can attempt to enumerate its SSO configurations.
3. **`pk_test_...` keys.** If any `pk_test_` publishable keys appear in source code, they indicate development-mode Clerk configuration, which provides weaker guarantees than production keys.

Confidence is Low because this finding requires grep confirmation against the source — the spec cites docs only. The actual presence of hardcoded dev keys in source code cannot be confirmed from the documents read.

---

## Impact

- **If hardcoded in source:** Dev Clerk tenant `endless-fly-19` used in production → dev-mode auth with potentially weaker security guarantees.
- **Public disclosure of dev tenant:** Competitor or attacker knows the dev Clerk tenant domain and can enumerate its public SSO configuration.
- **No direct exploitability** from the docs reference alone.

---

## Exploit scenario

**If `pk_test_endless-fly-19...` is in source code:**
1. Source code is publicly visible or leaked.
2. Attacker extracts `pk_test_...` key.
3. Attacker constructs JWTs using the development Clerk tenant.
4. If the gateway uses the dev tenant key in production, attacker can forge valid JWTs.

**Enumeration from docs alone:**
Not directly exploitable.

---

## Affected surface

- Files: `signalpilot/web/enterprise-connections.md:36` (docs), potentially source files
- Endpoints: Not applicable (docs only)
- Auth modes: Cloud mode (if dev key used in production)

---

## Recommended actions

**Step 1: Grep for the dev tenant identifier:**

```bash
grep -rn "endless-fly-19" /home/agentuser/repo/ \
  --include="*.ts" --include="*.tsx" --include="*.py" --include="*.env" \
  --include="*.json" --include="*.yaml" --include="*.yml" \
  --exclude-dir=".git"

grep -rn "pk_test_" /home/agentuser/repo/ \
  --include="*.ts" --include="*.tsx" --include="*.py" --include="*.env" \
  --include="*.json" --include="*.yaml" --include="*.yml" \
  --exclude-dir=".git"
```

**Step 2: If found in source code:**
- Remove the hardcoded key.
- Use environment variables: `process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`.
- Rotate the dev Clerk tenant if it was ever used with production data.

**Step 3: Update docs:**
- Remove `endless-fly-19.clerk.accounts.dev` from `enterprise-connections.md`.
- Replace with `{your-org}.clerk.accounts.dev` as a placeholder.

---

## Proposed fix

```bash
# Verification grep (run by the fixing developer):
grep -rn "endless-fly-19\|pk_test_" \
  signalpilot/web/ signalpilot/gateway/ \
  --include="*.ts" --include="*.tsx" --include="*.py"
# If no results: finding is docs-only, severity confirmed as Info
# If results found: escalate to High (hardcoded dev credential)
```

Update `enterprise-connections.md:36` to remove the specific tenant hostname:

```markdown
<!-- Before: -->
See: https://endless-fly-19.clerk.accounts.dev/...

<!-- After: -->
See: https://{your-clerk-domain}/.well-known/...
```

---

## Verification / test plan

**Grep result (to be run by the team):**
```bash
grep -rn "endless-fly-19" . --exclude-dir=.git
# Expected result (Info level): only appears in enterprise-connections.md
# Unexpected result (escalate to High): appears in .ts/.py files
```

---

## Rollout / migration notes

- If only in docs: update docs, no code change needed.
- If in source code: remove, use env var, rotate dev Clerk tenant.
- No data migration either way.
