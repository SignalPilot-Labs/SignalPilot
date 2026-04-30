# Any URL not matched by an API router falls through to the MCP ASGI app — surface enumeration and middleware skew

- Slug: unmatched-paths-fall-through-to-mcp-app
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/main.py:331`, `signalpilot/gateway/gateway/middleware.py:135-138`

Back to [issues.md](issues.md)

---

## Problem

The MCP HTTP app is mounted at the root path:

```python
# main.py:331
app.mount("/", _mcp_http_app)
logger.info("MCP streamable-http endpoint mounted at /mcp")
```

The log claims `/mcp`, but the actual mount path is `/`. This means any path the FastAPI router does not match is forwarded to `_mcp_http_app` — including paths the operator never intended to expose to MCP.

Compounding this, `APIKeyAuthMiddleware` only short-circuits for paths starting with `/mcp`:

```python
# middleware.py:135-138
# MCP endpoints have their own auth (MCPAuthMiddleware) — skip
if request.url.path.startswith("/mcp"):
    return await call_next(request)
```

So a request like `GET /random-path`:

1. Hits `APIKeyAuthMiddleware`. Path is not `/mcp`, so the middleware demands API key auth.
2. If the request has a valid API key → middleware sets `request.state.auth` and calls `call_next`.
3. No FastAPI route matches `/random-path`.
4. Falls through to the mounted MCP app, which then runs `MCPAuthMiddleware` *again*, possibly with different IP-extraction semantics (see finding 60), and tries to dispatch the path as an MCP request.

The double-middleware path means MCP audit rows can be written for non-MCP paths, and any error responses originate from the MCP layer, leaking implementation details (FastMCP version strings, JSON-RPC framing).

This is round-1 finding 43's expansion: the comment vs. mount-path mismatch has concrete behavioral consequences.

---

## Impact

- Information disclosure: unmatched paths return MCP framing errors (e.g. `"jsonrpc": "2.0"` shaped messages), revealing the internal stack.
- Audit pollution: MCP audit code paths fire for paths that aren't MCP requests.
- Defense-in-depth: a future router bug (e.g. typo `/api/quere`) silently degrades to the MCP transport rather than 404-ing.

---

## Exploit scenario

```bash
curl https://gateway.signalpilot.ai/foo \
  -H "Authorization: Bearer <valid-key>"
```

Response body contains MCP/JSON-RPC framing rather than a clean 404. Repeating with various paths enumerates the FastMCP version and behavior.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/main.py:331`, `signalpilot/gateway/gateway/middleware.py:135-138`.
- Endpoints: every URL that does not match a FastAPI route.
- Auth modes: any authenticated request, cloud + local.

---

## Proposed fix

- Mount the MCP app at `/mcp` explicitly: `app.mount("/mcp", _mcp_http_app)`.
- Update the `APIKeyAuthMiddleware` skip predicate accordingly (already correct: `startswith("/mcp")`).
- Add a catch-all route that returns 404 with no body:
  ```python
  @app.get("/{full_path:path}")
  async def _catch_all(full_path: str):
      raise HTTPException(404)
  ```
- Add a unit test that asserts `GET /unknown-path` returns 404 and not MCP-shaped output.

---

## Verification / test plan

- Unit: `tests/test_mcp_mount.py::test_unmatched_path_returns_404`.
- Manual: `curl /foo` → 404, no JSON-RPC envelope.
- Fixed when MCP app's reach is bounded to `/mcp/*`.

---

## Rollout / migration notes

- Existing MCP clients already POST to `/mcp` (the FastMCP transport default), so behavior should be unchanged from their perspective.
- Rollback: re-mount at root; non-destructive.
