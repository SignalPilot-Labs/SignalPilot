# JWT decoding does not enforce `nbf`/`iat` constraints or set leeway

- Slug: clerk-jwt-no-clock-leeway-or-nbf-check
- Severity: Medium
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/gateway/gateway/auth.py:108-127`

Back to [issues.md](issues.md)

---

## Problem

The `jwt.decode` call in `resolve_user_id` verifies the `exp` claim (PyJWT default) and the `iss` claim, but:

1. **`nbf` (not-before) claim is not enforced if absent.** PyJWT's default behavior is to check `nbf` if present but not require it. A Clerk token issued without `nbf` is accepted immediately with no time lower bound.
2. **No `leeway` is configured.** In distributed systems, small clock skew between the gateway pod and Clerk's servers can cause valid tokens to be rejected (`exp` in the past by 1-2 seconds) or not-yet-valid tokens to be accepted (`nbf` in the future by 1-2 seconds). The absence of leeway means legitimate users may get spurious 401s during clock skew events.
3. **No `jti` (JWT ID) replay check.** Clerk tokens are short-lived but there is no server-side blacklist or replay prevention. A token exfiltrated via XSS or network interception can be replayed until its `exp` with no server-side revocation short of Clerk's own session revocation.
4. **No `iat` (issued-at) freshness check.** Tokens could theoretically be issued with a very old `iat` if Clerk's session is not invalidated.

The practical risk of items 3 and 4 is low given Clerk's short token TTLs (1 hour by default) and the mitigating control of Clerk session revocation. However, items 1 and 2 represent a more immediate concern.

---

## Impact

- An exfiltrated Clerk JWT (e.g., via XSS in a tenant-controlled page, or a MITM attack on an HTTP endpoint) can be replayed for the full token lifetime (~1 hour) without any server-side countermeasure.
- Clock skew exceeding the PyJWT default tolerance (~0s) can cause spurious auth failures for valid users.
- Combined with the missing `aud` check (finding [clerk-jwt-audience-not-verified](clerk-jwt-audience-not-verified-proposal.md)), the attack surface for token confusion is broader.

---

## Exploit scenario

1. Attacker finds an XSS vector in the SignalPilot web app (e.g., via unsanitized query result rendering — related to finding [csp-allows-unsafe-inline-and-unsafe-eval](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md)).
2. XSS payload reads `__session` cookie or intercepts the token from `localStorage` / in-memory Clerk state.
3. Attacker exfiltrates the JWT.
4. Attacker replays the token against the gateway for up to 1 hour after exfiltration.
5. Victim's Clerk session revocation (e.g., via `revokeSession`) does NOT invalidate the JWT — it prevents new token issuance but the already-issued JWT remains valid until `exp`.
6. No server-side mechanism stops the replay.

```bash
# Replay exfiltrated token
curl https://gateway.signalpilot.ai/api/query \
  -H "Authorization: Bearer <exfiltrated-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"connection_name":"prod","query":"SELECT * FROM salaries"}'
```

---

## Affected surface

- Files: `signalpilot/gateway/gateway/auth.py:108-127`
- Endpoints: All endpoints in cloud mode that depend on `UserID` / `OrgID`
- Auth modes: Cloud mode JWT path only

---

## Proposed fix

```python
# auth.py — updated jwt.decode call:
import jwt as pyjwt

LEEWAY_SECONDS = 30  # configurable via SP_JWT_LEEWAY env var

claims = pyjwt.decode(
    token,
    signing_key.key,
    algorithms=["RS256"],
    issuer=_expected_issuer,
    audience=EXPECTED_AUDIENCE,  # see audience finding
    leeway=datetime.timedelta(seconds=LEEWAY_SECONDS),
    options={
        "require": ["exp", "iat", "sub"],  # require presence of these claims
        # nbf is optional in Clerk tokens; do not require but verify if present
    },
)
```

For replay protection, document that revocation requires Clerk session revocation (which prevents new token issuance) and accept the residual window as a known limitation. If stronger revocation is needed, implement a short-lived token denylist keyed by `jti` (Redis TTL = token `exp`).

New invariant: `exp`, `iat`, and `sub` claims are required. Missing any of them raises 401.

---

## Verification / test plan

**Unit tests:**
1. `test_jwt_missing_exp_rejected` — omit `exp` from JWT claims, assert 401.
2. `test_jwt_missing_sub_rejected` — omit `sub`, assert 401.
3. `test_jwt_clock_skew_within_leeway` — token expired 15s ago, assert accepted.
4. `test_jwt_clock_skew_outside_leeway` — token expired 60s ago, assert 401.

**Manual checklist:**
- Use `pyjwt` locally to mint a token with no `nbf` claim. Verify gateway accepts it (currently does, should still after fix since `nbf` is optional).
- Mint a token with `exp` 1 day in the past. Before fix: may produce JWT error. After fix with leeway: still rejected (leeway of 30s does not help here).

---

## Rollout / migration notes

- No data migration needed.
- Leeway of 30s is safe for NTP-synchronized clusters. Increase if gateway pods have poor clock sync.
- Customer-visible impact: none if clock sync is healthy. If clock skew exceeds 30s, legitimate users already experience 401s.
- Rollback: remove the `leeway` and `options` parameters; behavior reverts to PyJWT defaults.

**Related findings:** [clerk-jwt-audience-not-verified](clerk-jwt-audience-not-verified-proposal.md)
