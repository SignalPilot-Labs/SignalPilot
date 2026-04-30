# In-memory `_active_sandboxes` is a process-global dict shared across all tenants

- Slug: sandboxes-store-not-org-scoped
- Severity: High
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:561-582`, `signalpilot/gateway/gateway/api/sandboxes.py:24-107`

Back to [issues.md](issues.md)

---

## Problem

Sandbox state is maintained in a module-global dictionary with no tenant isolation:

```python
# store.py:563
_active_sandboxes: dict[str, SandboxInfo] = {}

def list_sandboxes() -> list[SandboxInfo]:
    return list(_active_sandboxes.values())  # returns ALL sandboxes

def get_sandbox(sandbox_id: str) -> SandboxInfo | None:
    return _active_sandboxes.get(sandbox_id)  # no org check
```

The API endpoints call these functions directly:

```python
# api/sandboxes.py:24-26
@router.get("/sandboxes", dependencies=[RequireScope("read")])
async def get_sandboxes(_: UserID):
    return list_sandboxes()  # returns sandboxes from ALL tenants

# api/sandboxes.py:55-60
@router.get("/sandboxes/{sandbox_id}", dependencies=[RequireScope("read")])
async def get_sandbox_detail(_: UserID, sandbox_id: str):
    sandbox = get_sandbox(sandbox_id)  # no org_id check
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return sandbox

# api/sandboxes.py:76-107
@router.post("/sandboxes/{sandbox_id}/execute", dependencies=[RequireScope("execute")])
async def execute_in_sandbox(sandbox_id: str, req: ExecuteRequest, store: StoreD):
    sandbox = get_sandbox(sandbox_id)  # no org_id check — executes in any tenant's sandbox
```

`SandboxInfo` is a dataclass that includes `connection_name` (a reference to a connection belonging to another tenant's organization). An attacker who learns or guesses a sandbox UUID can execute Python code in that sandbox, which runs queries against the connection that was bound when the sandbox was created — i.e., the attacker's code runs against a different tenant's database connection.

---

## Impact

- **Cross-tenant sandbox execution:** Authenticated tenant B can execute code in tenant A's sandbox, which is connected to tenant A's database. This is remote code execution in the context of another tenant's data.
- **Cross-tenant sandbox enumeration:** `GET /api/sandboxes` returns all active sandboxes across all organizations, leaking sandbox IDs, labels, connection names, and status.
- **Cross-tenant sandbox deletion:** `DELETE /api/sandboxes/{id}` can terminate another tenant's sandbox.
- Multi-tenant blast radius: all currently active sandboxes in the gateway process are affected.

---

## Exploit scenario

1. Tenant A (victim) creates a sandbox connected to their production Postgres database: `POST /api/sandboxes` → returns `{"id": "abc-123-def"}`.
2. Tenant B (attacker) calls `GET /api/sandboxes` with their own valid API key.
3. Response includes Tenant A's sandbox: `{"id": "abc-123-def", "connection_name": "acme-prod", ...}`.
4. Tenant B executes against it:

```bash
curl -X POST https://gateway.signalpilot.ai/api/sandboxes/abc-123-def/execute \
  -H "X-API-Key: sp_tenant_b_key" \
  -H "Content-Type: application/json" \
  -d '{"code": "import duckdb; conn = duckdb.connect(); conn.execute(\"SELECT * FROM acme_customers\").fetchall()"}'
```

5. The sandbox executes in the context of Tenant A's connection, returning Tenant A's data to Tenant B.

Note: sandbox is disabled in cloud mode per `main.py:87`, but the code path exists and would be exploitable if sandbox is ever re-enabled in cloud or in an on-premises enterprise deployment.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:561-582`, `signalpilot/gateway/gateway/api/sandboxes.py:24-107`
- Endpoints: `GET /api/sandboxes`, `GET /api/sandboxes/{id}`, `POST /api/sandboxes`, `DELETE /api/sandboxes/{id}`, `POST /api/sandboxes/{id}/execute`
- Auth modes: Cloud mode (any authenticated user) and local mode

---

## Proposed fix

Add `org_id` to `SandboxInfo` and filter all operations:

```python
# models.py — update SandboxInfo:
@dataclass
class SandboxInfo:
    id: str
    org_id: str  # ADD THIS FIELD
    connection_name: str
    label: str
    status: str
    vm_id: str | None
    budget_usd: float | None
    row_limit: int | None
    created_at: float

# store.py — scoped helpers:
def list_sandboxes(org_id: str) -> list[SandboxInfo]:
    return [s for s in _active_sandboxes.values() if s.org_id == org_id]

def get_sandbox(sandbox_id: str, org_id: str) -> SandboxInfo | None:
    sandbox = _active_sandboxes.get(sandbox_id)
    if sandbox is None or sandbox.org_id != org_id:
        return None
    return sandbox

# api/sandboxes.py — pass org_id from store:
@router.get("/sandboxes", dependencies=[RequireScope("read")])
async def get_sandboxes(store: StoreD):
    return list_sandboxes(store.org_id or raise_if_cloud())

@router.get("/sandboxes/{sandbox_id}", dependencies=[RequireScope("read")])
async def get_sandbox_detail(sandbox_id: str, store: StoreD):
    sandbox = get_sandbox(sandbox_id, store.org_id or raise_if_cloud())
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return sandbox
```

Also update `create_sandbox` to populate `org_id` from `store.org_id`.

---

## Verification / test plan

**Unit tests:**
1. `test_list_sandboxes_org_scoped` — create sandboxes for two orgs, assert each org only sees its own.
2. `test_get_sandbox_cross_tenant_returns_404` — tenant B requests tenant A's sandbox_id, assert 404.
3. `test_execute_cross_tenant_returns_404` — tenant B POSTs execute to tenant A's sandbox, assert 404.

**Manual checklist:**
- Create two test API keys for different orgs.
- With key A, create a sandbox. Record the sandbox ID.
- With key B, call `GET /api/sandboxes` — should not include sandbox from org A.
- With key B, call `POST /api/sandboxes/{id_from_org_a}/execute` — should return 404.

---

## Rollout / migration notes

- In-memory store only; no database migration required.
- Existing sandboxes in flight during deployment will lose their `org_id` context (they would need a restart to populate). This is acceptable since sandboxes are ephemeral.
- **Cloud mode note:** Sandbox is disabled in cloud today (`main.py:87`). This fix must be in place before sandbox is re-enabled in cloud.
- Rollback: revert the `org_id` additions. Functionally equivalent to current behavior.

**Related findings:** [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md), [scope-guard-bypass-for-jwt-requests](scope-guard-bypass-for-jwt-requests-proposal.md)
