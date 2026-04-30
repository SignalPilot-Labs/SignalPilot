# Clerk JWT signature verified but `aud` claim ignored

- Slug: clerk-jwt-audience-not-verified
- Severity: High
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/auth.py:110-116`, all cloud-mode API endpoints requiring JWT auth

Back to [issues.md](issues.md)

---

## Problem

In `resolve_user_id`, the gateway decodes Clerk JWTs using PyJWT with `options={"verify_aud": False}`:

```python
# auth.py:110-116
claims = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    issuer=_expected_issuer,
    options={"verify_aud": False},
)
```

The `aud` (audience) claim identifies which service a token was issued for. Clerk supports multiple JWT templates per tenant, each with a configurable `aud`. By skipping audience verification, the gateway will accept any token signed by the Clerk tenant's private key, regardless of which service it was intended for.

This means:
- A Clerk JWT template configured for a third-party service (e.g., `aud: "third-party-analytics"`) can be presented to the gateway and will be accepted.
- OAuth tokens minted via `getToken({template: "..."})`  for unrelated integrations within the same Clerk tenant are accepted.
- An `aud` claim of `""`, `null`, or any attacker-controlled value passes without rejection.

Clerk's documentation explicitly recommends validating `aud` to prevent cross-service token confusion attacks.

---

## Impact

- Any user in the same Clerk tenant who obtains a JWT for any purpose (including tokens intended for third-party integrations, mobile apps, or internal services) can present that token to the gateway and gain full API access as themselves.
- In a B2B SaaS context where customers use Clerk, a customer's developer who obtains a template token for their own internal tooling could access the SignalPilot gateway as a valid org member.
- Scope of the bypass: the JWT still contains the correct `sub` (user ID) and `org_id`, so this is not a cross-user attack, but it weakens the "this token was issued specifically for the gateway" guarantee and enables token confusion across services sharing a Clerk tenant.

---

## Exploit scenario

1. Attacker is a legitimate member of an organization using SignalPilot.
2. The organization's Clerk tenant has a JWT template called `for-internal-dashboard` with `aud: "internal-dashboard"`.
3. Attacker uses `clerk.session.getToken({template: "for-internal-dashboard"})` in the browser to obtain a JWT.
4. This token is signed by Clerk and contains valid `sub` and `org_id` claims.
5. Attacker presents the token to the gateway:

```bash
curl https://gateway.signalpilot.ai/api/connections \
  -H "Authorization: Bearer <token-for-internal-dashboard>"
```

6. Gateway verifies the signature (valid), verifies the issuer (matches), skips `aud` verification, and grants access.
7. Attacker now has full gateway access using a token that was never meant for the gateway.

The practical risk in a single-purpose Clerk tenant (only SignalPilot) is lower, but in shared-tenant or platform deployments this is exploitable today.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/auth.py:110-116`
- Endpoints: All endpoints requiring `UserID` or `OrgID` dependencies in cloud mode
- Auth modes: Cloud mode only; local mode does not use JWTs

---

## Proposed fix

Set an explicit expected audience and pass it to `jwt.decode`:

```python
# auth.py — in resolve_user_id:
EXPECTED_AUDIENCE = os.environ.get("CLERK_JWT_AUDIENCE", "signalpilot-gateway")

claims = jwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    issuer=_expected_issuer,
    audience=EXPECTED_AUDIENCE,
    # Remove options={"verify_aud": False}
)
```

In the Clerk dashboard, configure the JWT template used by the gateway with `aud: "signalpilot-gateway"` (or the value set in `CLERK_JWT_AUDIENCE`).

New invariants:
- `CLERK_JWT_AUDIENCE` must be set in cloud mode; fail startup if absent.
- Document in the deployment guide that the Clerk JWT template must include `aud: signalpilot-gateway`.

Backward-compatibility notes:
- **Existing sessions will be rejected** until the Clerk JWT template is updated to include the matching `aud` claim. This is a breaking change requiring a coordinated deploy:
  1. Update the Clerk JWT template to add `aud: "signalpilot-gateway"`.
  2. Deploy the gateway change.
  3. Existing browser sessions will get a new token on the next refresh (Clerk rotates tokens on reload).
- Alternatively, support a transition period where both `verify_aud=True` with the correct audience, and `verify_aud=False` are accepted for 24h using a feature flag `SP_CLERK_STRICT_AUD`.

---

## Verification / test plan

**Unit tests to add:**
1. `test_jwt_wrong_audience_rejected` — construct a JWT with `aud="wrong-service"`, assert `resolve_user_id` raises 401.
2. `test_jwt_correct_audience_accepted` — JWT with `aud="signalpilot-gateway"`, assert accepted.
3. `test_jwt_missing_audience_rejected` — JWT with no `aud` claim, assert rejected.

**Manual repro checklist:**
- Create a second JWT template in Clerk with `aud: "other-service"`.
- Obtain a token using that template.
- Before fix: `GET /api/connections` returns 200. After fix: returns 401.

**What "fixed" looks like:**
```python
# In test — mock jwt.decode to return claims without correct aud
# Ensure HTTPException(401) is raised
```

---

## Rollout / migration notes

- **Order of operations:**
  1. Update Clerk JWT template to include `aud: "signalpilot-gateway"`.
  2. Set `CLERK_JWT_AUDIENCE=signalpilot-gateway` in gateway environment.
  3. Deploy gateway.
- **Customer-visible impact:** Browser sessions will seamlessly pick up the new `aud` claim on next token refresh. No action required from end users if Clerk template is updated before or simultaneously with gateway deploy.
- **Rollback plan:** Remove `CLERK_JWT_AUDIENCE` env var and revert the `jwt.decode` call. Users are unaffected.

**Related findings:** [clerk-jwt-no-clock-leeway-or-nbf-check](clerk-jwt-no-clock-leeway-or-nbf-check-proposal.md)
