# `app.mount("/", _mcp_http_app)` mounts the MCP ASGI app at root, not `/mcp`

- Slug: mcp-mounted-at-root-instead-of-mcp-prefix-only
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/main.py:331`

Back to [issues.md](issues.md)

---

## Problem

The MCP ASGI app is mounted at the root path, not at `/mcp` as the log message claims:

```python
# main.py:331
app.mount("/", _mcp_http_app)
logger.info("MCP streamable-http endpoint mounted at /mcp")  # <-- misleading comment
```

In FastAPI, `app.mount("/")` is a catch-all: any path not matched by a registered API router falls through to the MCP app. This has several consequences:

1. **Information disclosure:** The MCP app receives all unmatched requests. If the MCP implementation responds to unrecognized paths with version banners, capability lists, or error messages that reveal implementation details, attackers can use these as a reconnaissance tool.
2. **Auth model complexity:** `MCPAuthMiddleware` decides whether to authenticate based on path-internal logic. With a catch-all mount, every unmatched path goes through the MCP auth middleware. A path typo in a request (`/api/queryy` instead of `/api/query`) silently falls through to MCP auth instead of returning a clean 404.
3. **Future route shadowing:** Any new FastAPI route added after `app.mount("/")` would be silently ignored (routes registered after a catch-all mount are unreachable). In FastAPI's routing, `mount("/")` captures everything not previously matched, but if a developer adds a router after this line, those routes will not be reachable.
4. **Debug/health endpoint leak:** If MCP responds to `GET /health` or `GET /metrics` before the registered health route, the MCP response may be returned instead of the expected gateway health response.

---

## Impact

- Reconnaissance via unmatched paths: MCP may respond with version info or capability listings to crafted paths.
- Auth model confusion: developers reviewing code see `mount("/")` and may not realize all unmatched paths go through MCP auth.
- Future route shadowing if routes are added after the mount.

---

## Exploit scenario

**Reconnaissance:**
```bash
# Attacker sends requests to non-existent paths:
curl https://gateway.signalpilot.ai/does-not-exist
# Falls through to MCP, which may return:
# {"error": "Unknown method", "server": "mcp-server/1.0", ...}
# Reveals server type and version
```

**Auth bypass via path confusion:**
```bash
# Legitimate endpoint: /api/query (registered router)
# Typo: /api/queryy (not registered → falls to MCP)
curl https://gateway.signalpilot.ai/api/queryy \
  -H "Authorization: Bearer fake-not-a-real-jwt"
# MCPAuthMiddleware runs; if "no keys" bypass is triggered, request passes
```

---

## Affected surface

- Files: `signalpilot/gateway/gateway/main.py:331`
- Endpoints: All unmatched paths (catch-all behavior)
- Auth modes: Cloud and local

---

## Proposed fix

Mount at `/mcp` explicitly and let unmatched paths return 404:

```python
# main.py:
app.mount("/mcp", _mcp_http_app)  # Mount at /mcp only
logger.info("MCP streamable-http endpoint mounted at /mcp")  # Now accurate

# Optional: Add explicit 404 handler for unmatched paths
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(path: str):
    raise HTTPException(status_code=404, detail=f"Path /{path} not found")
```

Update `MCPAuthMiddleware` to validate the path starts with `/mcp`:

```python
# mcp_auth.py:MCPAuthMiddleware.__call__:
if scope["type"] == "http":
    path = scope.get("path", "")
    if not path.startswith("/mcp"):
        # This should not happen if mounted at /mcp, but defense-in-depth:
        await _send_404(send)
        return
```

Update all MCP client configurations to use `https://gateway.signalpilot.ai/mcp` as the endpoint.

---

## Verification / test plan

**Unit tests:**
1. `test_unmatched_path_returns_404` — request to `/nonexistent`, assert 404 (not MCP response).
2. `test_mcp_path_reaches_mcp_app` — request to `/mcp`, assert MCP response.
3. `test_api_path_reaches_api_router` — request to `/api/keys`, assert API response.

**Manual checklist:**
- Send `GET https://gateway.signalpilot.ai/does-not-exist`.
- Before fix: MCP response (200 or MCP error).
- After fix: clean 404 JSON.

---

## Rollout / migration notes

- **Client update required:** The Claude Code plugin and any MCP client configuration pointing to `https://gateway.signalpilot.ai/` (root) must be updated to `https://gateway.signalpilot.ai/mcp`.
- The plugin documentation and `README.md` must be updated to reflect the new endpoint.
- Rollback: revert to `app.mount("/")`.
