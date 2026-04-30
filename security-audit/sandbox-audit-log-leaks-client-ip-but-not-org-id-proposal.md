# Sandbox audit logs lack `org_id` / `key_id` correlation fields

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: sandbox-audit-log-leaks-client-ip-but-not-org-id
- Severity: Low
- Cloud impact: Partial
- Confidence: High
- Affected files / endpoints: `sp-sandbox/audit.py:27-66`

Back to [issues.md](issues.md)

---

## Problem

The sandbox manager's audit logging captures execution events but only records client IP, session token prefix, and code hash — not the org_id or key_id of the requesting tenant:

```python
# sp-sandbox/audit.py:27-66 (approximate)
def log_execution(
    session_token: str,
    vm_id: str,
    code_length: int,
    code_hash: str,
    timeout: int,
    mount_count: int,
    success: bool,
    error: str | None,
    execution_ms: float,
    client_ip: str | None,
) -> None:
    # Logs: session_token prefix, vm_id, client_ip, code_hash, success
    # Does NOT log: org_id, key_id, user_id
```

The gateway passes `session_token` (a UUID generated per call) when requesting sandbox execution, but does not pass the `org_id` or `key_id` of the authenticated user. The sandbox manager never receives this information.

Post-incident correlation requires:
1. Find the sandbox audit log entry by session_token prefix.
2. Find the gateway audit log entry with the same session_token.
3. The gateway audit log contains the key_id/org_id.

This two-hop correlation is slow and error-prone, and requires both log sources to be available and correlated on the same time axis.

---

## Impact

- Incident response delay: attributing a malicious sandbox execution to a specific org/user requires cross-referencing two separate log systems.
- Forensic gaps: if the gateway log is unavailable (log rotation, different retention policy), sandbox executions cannot be attributed.
- Compliance risk: audit trails for sandbox executions are incomplete from a per-tenant perspective.

---

## Affected surface

- Files: `sp-sandbox/audit.py:27-66`, `signalpilot/gateway/gateway/sandbox_client.py`
- Endpoints: `POST /execute` on sandbox manager
- Auth modes: Local mode (sandbox disabled in cloud)

---

## Proposed fix

Pass `org_id` and `key_id` from the gateway to the sandbox manager as request fields, and include them in audit log entries:

```python
# sandbox_manager.py:execute_handler — accept new fields:
org_id = body.get("org_id", "")
key_id = body.get("key_id", "")

audit.log_execution(
    session_token=session_token,
    vm_id=result.vm_id,
    org_id=org_id,    # NEW
    key_id=key_id,    # NEW
    ...
)

# sp-sandbox/audit.py — updated log_execution:
def log_execution(
    session_token: str,
    vm_id: str,
    org_id: str,      # NEW
    key_id: str,      # NEW
    ...
) -> None:
    entry = {
        "timestamp": ...,
        "session_token_prefix": session_token[:8] + "...",
        "org_id": org_id,    # NEW
        "key_id": key_id,    # NEW
        "client_ip": client_ip,
        ...
    }
```

On the gateway side, pass the org/key context:

```python
# signalpilot/gateway/gateway/sandbox_client.py:
async def execute(self, sandbox, code, session_token, timeout, org_id="", key_id=""):
    payload = {
        "code": code,
        "session_token": session_token,
        "org_id": org_id,
        "key_id": key_id,
        ...
    }
```

---

## Verification / test plan

**Unit tests:**
1. `test_audit_log_includes_org_id` — execute handler with org_id, verify audit log entry contains org_id.
2. `test_audit_log_key_id_present` — assert key_id field in logged entry.

**Manual checklist:**
- Execute sandbox code via API.
- Check sandbox audit log file.
- Verify entry includes `org_id` and `key_id` fields.

---

## Rollout / migration notes

- Backward-compatible addition (new optional fields in request body and log).
- Old log entries without `org_id`/`key_id` remain valid; new entries will have them.
- No DB migration (audit logs are file-based in the sandbox).
