# `sandbox_manager.py /execute` accepts any session_token; one tenant can execute under another tenant's session_token if guessed

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: sandbox-execute-no-tenant-binding
- Severity: Medium
- Cloud impact: Partial
- Confidence: High
- Affected files / endpoints: `sp-sandbox/sandbox_manager.py:56-216`

Back to [issues.md](issues.md)

---

## Problem

The sandbox manager exposes an HTTP API (`POST /execute`, `DELETE /vm/{vm_id}`, `GET /vms`) with no authentication:

```python
# sandbox_manager.py:56-65
async def execute_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)

    code = body.get("code", "")
    session_token = body.get("session_token", "")
    ...
    # No authentication check anywhere in this function
```

The sandbox manager is intended to be accessible only from the gateway container via the internal Docker network (`SP_SANDBOX_MANAGER_URL: http://sandbox:8080`). Network-level isolation is the sole protection.

Problems:
1. **No shared-secret authentication.** If the sandbox container's port 8080 is ever exposed (accidental `ports:` addition, a misconfigured ingress rule, or a container network misconfiguration), any caller can execute arbitrary Python code.
2. **`session_token` is not tied to a tenant.** The `session_token` in `active_sessions` is a `str -> vm_id` map with no org context. If two tenants have overlapping session tokens (e.g., both use a fixed token for testing), they could interfere.
3. **`GET /vms` lists all active sandboxes.** If accessible to an attacker, this reveals all active session token prefixes and VM IDs across all tenants.

---

## Impact

- **Network exposure:** If port 8080 is accidentally exposed, unauthenticated remote code execution on the gateway host (inside gVisor, but gVisor has had escapes historically).
- **Session token collision:** Low risk since gateway generates UUIDs, but an explicit tenant binding would prevent any future code from using predictable tokens.
- **Cloud:** Sandbox is currently disabled in cloud mode; risk is primarily for enterprise on-premises and local deployments.

---

## Exploit scenario

**Accidental port exposure:**
1. A Docker Compose override adds `ports: ["8080:8080"]` to the sandbox service.
2. Attacker discovers the open port (nmap, shodan).
3. Attacker sends:

```bash
curl -X POST http://victim-host:8080/execute \
  -H "Content-Type: application/json" \
  -d '{
    "code": "import subprocess; result = subprocess.run([\"id\"], capture_output=True); print(result.stdout)",
    "session_token": "attacker-token",
    "timeout": 30
  }'
# Executes within gVisor but demonstrates the attack surface
```

4. Within gVisor, attacker has a Python execution environment with access to mounted files (if any are mounted).

---

## Affected surface

- Files: `sp-sandbox/sandbox_manager.py:56-216`
- Endpoints: `POST /execute`, `GET /vms`, `DELETE /vm/{vm_id}`, `GET /files`
- Auth modes: No auth (network isolation only)

---

## Proposed fix

Add a shared-secret header authentication to all sandbox manager endpoints:

```python
# sandbox_manager.py — add to all handlers:
import os
import hmac as _hmac

SANDBOX_AUTH_TOKEN = os.environ.get("SP_SANDBOX_TOKEN", "")

def _check_auth(request: web.Request) -> bool:
    """Verify X-Sandbox-Auth header matches SP_SANDBOX_TOKEN."""
    if not SANDBOX_AUTH_TOKEN:
        # Token not set — only allow from localhost for dev mode
        return request.remote in ("127.0.0.1", "::1")
    provided = request.headers.get("X-Sandbox-Auth", "")
    return _hmac.compare_digest(provided, SANDBOX_AUTH_TOKEN)

async def execute_handler(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    ...
```

On the gateway side, send the token:

```python
# signalpilot/gateway/gateway/sandbox_client.py — when calling sandbox:
headers = {}
sandbox_token = os.environ.get("SP_SANDBOX_TOKEN", "")
if sandbox_token:
    headers["X-Sandbox-Auth"] = sandbox_token
response = await http_client.post(url, json=payload, headers=headers)
```

Generate a random token at startup:
```yaml
# docker-compose.yml:
sandbox:
  environment:
    SP_SANDBOX_TOKEN: "${SP_SANDBOX_TOKEN}"
gateway:
  environment:
    SP_SANDBOX_TOKEN: "${SP_SANDBOX_TOKEN}"
```

---

## Verification / test plan

**Unit tests:**
1. `test_execute_no_auth_header_returns_401` — request without `X-Sandbox-Auth`, assert 401.
2. `test_execute_wrong_auth_returns_401` — wrong token, assert 401.
3. `test_execute_correct_auth_succeeds` — correct token, assert success.

**Manual checklist:**
- Start sandbox with `SP_SANDBOX_TOKEN=test-secret`.
- Send `POST /execute` without the header: expect 401.
- Send with `X-Sandbox-Auth: test-secret`: expect success.

---

## Rollout / migration notes

- Generate `SP_SANDBOX_TOKEN` with `openssl rand -hex 32` and set in both gateway and sandbox containers.
- In local dev mode (no token set), allow localhost-only access — acceptable for developer laptops.
- Rollback: remove the `_check_auth` call from all handlers.
