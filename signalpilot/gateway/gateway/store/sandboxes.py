"""In-memory sandbox registry (org-scoped, ephemeral)."""

from __future__ import annotations

from gateway.models import SandboxInfo

_active_sandboxes: dict[str, SandboxInfo] = {}


def list_sandboxes(org_id: str) -> list[SandboxInfo]:
    return [s for s in _active_sandboxes.values() if s.org_id == org_id]


def get_sandbox(sandbox_id: str, org_id: str) -> SandboxInfo | None:
    sb = _active_sandboxes.get(sandbox_id)
    if sb is None or sb.org_id != org_id:
        return None
    return sb


def upsert_sandbox(sandbox: SandboxInfo) -> None:
    _active_sandboxes[sandbox.id] = sandbox


def delete_sandbox(sandbox_id: str, org_id: str) -> bool:
    sb = _active_sandboxes.get(sandbox_id)
    if sb is None or sb.org_id != org_id:
        return False
    del _active_sandboxes[sandbox_id]
    return True
