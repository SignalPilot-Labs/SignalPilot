# All scope-protected endpoints grant ALL scopes to any JWT/cookie-authenticated request

- Slug: scope-guard-bypass-for-jwt-requests
- Severity: High
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/scope_guard.py:34-38`, all endpoints using `RequireScope`

Back to [issues.md](issues.md)

---

## Problem

`require_scopes` (and the `RequireScope` factory) grants all scopes to JWT-authenticated requests unconditionally:

```python
# scope_guard.py:34-38
auth = getattr(request.state, "auth", None)

# Case 1: JWT/Clerk user — no auth dict set by middleware.
if auth is None:
    return  # Grant all scopes — NO SCOPE CHECK
```

The `auth` attribute is `None` when a request comes in via JWT (Clerk token or Bearer without `sp_` prefix), because the FastAPI `APIKeyAuthMiddleware` sets `request.state.auth` only for API-key-authenticated requests. JWT-authenticated requests rely on `resolve_user_id` (called via the `UserID` dependency) to set claims.

The design intent is that JWT users (Clerk-authenticated via the browser) are trusted with all capabilities. This is documented in the comment: "Case 1: JWT/Clerk user."

The footgun is subtle: the code comment in `scope_guard.py:20-30` explicitly warns:

> "WARNING: Case 1 grants all scopes when auth is None, which occurs for JWT and cookie-authenticated requests before resolve_user_id runs. This means every scope-protected endpoint MUST also include a `_: UserID` or `store: StoreD` parameter dependency to ensure JWT verification actually runs in cloud mode. Endpoints without those dependencies will pass scope checks with an unverified (or fake) Bearer token."

In practice: if an endpoint declares only `dependencies=[RequireScope("admin")]` and does NOT also declare a `_user_id: UserID` or `store: StoreD` parameter, an unauthenticated request with a fake Bearer token (not starting with `sp_`) will:
1. Not trigger `APIKeyAuthMiddleware` (the token doesn't start with `sp_`).
2. `request.state.auth` is `None`.
3. `require_scopes` returns immediately (Case 1 — grant all).
4. `resolve_user_id` is never called (no `UserID` dependency on the endpoint).
5. The endpoint executes without any authentication.

---

## Impact

- Endpoints that declare only `RequireScope` without a `UserID` or `StoreD` dependency are callable by unauthenticated attackers.
- Even if no current endpoint has this exact configuration, the design is a footgun that will produce silent vulnerabilities in any future endpoint that follows the pattern `@router.post("/...", dependencies=[RequireScope("admin")])` without adding `_: UserID`.
- The warning comment in `scope_guard.py` mitigates the immediate risk but does not eliminate it — developers working under time pressure frequently miss inline comments.

---

## Exploit scenario

If a hypothetical endpoint exists:
```python
@router.delete("/api/sensitive-data", dependencies=[RequireScope("admin")])
async def delete_sensitive():
    # No UserID, no StoreD
    await do_destructive_thing()
```

```bash
curl -X DELETE https://gateway.signalpilot.ai/api/sensitive-data \
  -H "Authorization: Bearer fake-not-a-real-jwt"
# Returns 200 — no authentication performed
```

To confirm this for existing endpoints: audit all routes that appear in `RequireScope` declarations and verify each also has `UserID` or `StoreD` in its signature.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/scope_guard.py:34-38`
- Endpoints: Any endpoint using `RequireScope` without a `UserID`/`StoreD` parameter dependency
- Auth modes: Cloud mode (local mode is entirely trusted, so Case 2 applies)

---

## Proposed fix

Make `RequireScope` itself depend on `UserID` via FastAPI's dependency injection chain, so JWT verification always runs as part of scope checking:

```python
# scope_guard.py:
from .auth import UserID  # the Annotated[str, Depends(resolve_user_id)] type

def RequireScope(*scopes: str) -> Any:
    """FastAPI dependency factory that enforces BOTH authentication and scope."""
    async def _check(request: Request, _user_id: UserID) -> None:
        # _user_id triggers resolve_user_id, which verifies JWT in cloud mode
        require_scopes(request, *scopes)
    return Depends(_check)
```

With this change, any endpoint declaring `dependencies=[RequireScope("admin")]` automatically pulls in `UserID`, ensuring JWT verification always runs.

Remove the "Case 1 grants all scopes" carve-out from `require_scopes` (or keep it, but now it only runs AFTER JWT verification has already been enforced via the `_user_id` dependency):

```python
def require_scopes(request: Request, *required: str) -> None:
    auth = getattr(request.state, "auth", None)
    # After the fix, reaching here means resolve_user_id already ran.
    # auth is None only for valid JWT users; still correct to grant all scopes.
    if auth is None:
        return
    ...
```

New invariant: `RequireScope` always triggers JWT verification; scope grants for JWT users are still unconditional (Clerk-authenticated browser users get full access), but they must have a valid JWT.

---

## Verification / test plan

**Unit tests:**
1. `test_require_scope_no_auth_no_jwt_returns_401` — fake Bearer token, no UserID dep in endpoint, after fix: 401.
2. `test_require_scope_valid_jwt_grants_all` — valid Clerk JWT, assert endpoint proceeds.
3. `test_require_scope_api_key_insufficient_scope_returns_403` — API key without required scope, assert 403.

**Audit step:**
Run a grep to find all `RequireScope` usages and verify each endpoint has `UserID` or `StoreD`:
```bash
grep -n "RequireScope" signalpilot/gateway/gateway/api/*.py
# Cross-reference with presence of UserID/StoreD in same endpoint signature
```

After fix: this audit becomes unnecessary since `RequireScope` itself pulls in `UserID`.

---

## Rollout / migration notes

- No data migration.
- Breaking change: any endpoint currently missing the `UserID` dependency will now require authentication. This is the intended behavior — no legitimate use case should be calling a `RequireScope`-protected endpoint without a valid identity.
- Test all existing endpoints before deploying; a broad integration test suite covering the authentication layer is recommended.
- Rollback: revert `RequireScope` to the current implementation.
