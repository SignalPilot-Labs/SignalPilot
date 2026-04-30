# `OPTIONS` method bypasses rate-limit, API-key auth, and body-size middleware

- Slug: options-method-bypasses-rate-limit-and-body-size
- Severity: Info
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/middleware.py:51-54,127-129,287-289`

Back to [issues.md](issues.md)

---

## Problem

Three middlewares in the gateway short-circuit on `OPTIONS`:

```python
# RequestBodySizeLimitMiddleware (middleware.py:51-54)
if method in ("GET", "OPTIONS", "HEAD"):
    await self.app(scope, receive, send)
    return

# APIKeyAuthMiddleware (middleware.py:127-129)
if request.method == "OPTIONS":
    return await call_next(request)

# RateLimitMiddleware (middleware.py:287-289)
if request.method == "OPTIONS":
    return await call_next(request)
```

The intent is to let CORS preflight succeed without auth, which is correct. But the consequences are:

- **No rate limit on OPTIONS.** A client can fire unlimited preflight requests; each one allocates a request, hits CORS middleware, and the FastAPI router. With `allow_credentials=True` and a permissive origin list (finding 42), an attacker can amplify load against the gateway via OPTIONS bursts that consume CPU but never count against the per-IP bucket.
- **No body-size cap.** `OPTIONS` requests with a large body (technically allowed by HTTP/1.1) are accepted in full before the app handler decides to ignore it.
- **No auth.** Combined with the above, any pre-route side effect (logging middleware, metrics) runs for every OPTIONS request from anywhere on the internet.

This is mostly an information-level concern because OPTIONS responses are small and stateless. The amplification factor is low. The finding documents the asymmetry for completeness.

---

## Impact

- CPU amplification: ~100k OPTIONS rpm from a single attacker source IP is not throttled.
- Log volume: every OPTIONS request hits the logging path, growing the log bill.
- Probe: attackers can map the gateway's CORS posture (allowed origins, methods, headers) without leaving rate-limit traces.

---

## Exploit scenario

```bash
while true; do
  curl -s -o /dev/null -X OPTIONS https://gateway.signalpilot.ai/api/query \
    -H "Origin: https://attacker.example" \
    -H "Access-Control-Request-Method: POST" &
done
```

No 429 is ever returned; logs fill with OPTIONS lines.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/middleware.py:51-54,127-129,287-289`.
- Endpoints: every route (OPTIONS preflight).
- Auth modes: unauthenticated.

---

## Proposed fix

- Add a separate, generous, per-IP OPTIONS rate limit (e.g. 600 rpm) so legitimate browsers are unaffected but bursting is stopped.
- Apply the body size limit even to OPTIONS (most clients send empty bodies, the cap won't bite).
- Consider returning a static cached preflight response from the LB layer rather than hitting the gateway at all.

---

## Verification / test plan

- Unit: `tests/test_options_rate_limit.py::test_options_throttled_after_burst`.
- Manual: `for i in $(seq 1 1000); do curl -X OPTIONS ... ; done` — assert eventual 429.

---

## Rollout / migration notes

- No customer-visible impact under normal browser use.
- Rollback: remove OPTIONS bucket; non-destructive.
