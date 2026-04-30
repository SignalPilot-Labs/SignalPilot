"""Sandbox execution tools: execute_code, sandbox_status (cloud-gated)."""

from __future__ import annotations

import os as _os
import time
import uuid

import httpx

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _is_cloud, _store_session, mcp_org_id_var
from gateway.mcp.helpers import _get_sandbox_url
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MAX_CODE_LENGTH
from gateway.models import AuditEntry
from gateway.store import list_sandboxes

if not _is_cloud:

    @audited_tool(mcp)
    async def execute_code(code: str, timeout: int = 30) -> str:
        """
        Execute Python code in an isolated gVisor sandbox.

        The code runs in a secure, ephemeral gVisor sandbox with Python 3.12 and common
        stdlib modules pre-loaded (math, re, collections, datetime, etc.).
        Each execution gets a fresh sandbox that is destroyed after returning.
        Typical latency: ~300ms.

        Args:
            code: Python code to execute
            timeout: Max execution time in seconds (default 30)

        Returns:
            The stdout output from the code, or an error message.
        """
        # Cloud mode gate
        from gateway.runtime.mode import is_cloud_mode

        if is_cloud_mode():
            return "Error: Code execution is not available in cloud mode"

        # Input validation
        if not code or not code.strip():
            return "Error: Code cannot be empty."
        if len(code) > _MAX_CODE_LENGTH:
            return f"Error: Code exceeds maximum length ({_MAX_CODE_LENGTH} characters)."
        if timeout < 1 or timeout > 300:
            return "Error: Timeout must be between 1 and 300 seconds."

        sandbox_url = await _get_sandbox_url()

        _sbx_headers: dict[str, str] = {}
        _sbx_token = _os.environ.get("SP_SANDBOX_TOKEN", "")
        if _sbx_token:
            _sbx_headers["X-Sandbox-Auth"] = _sbx_token
        async with httpx.AsyncClient(timeout=timeout + 10, headers=_sbx_headers) as client:
            try:
                resp = await client.post(
                    f"{sandbox_url}/execute",
                    json={
                        "code": code,
                        "session_token": str(uuid.uuid4()),
                        "timeout": timeout,
                    },
                )
                data = resp.json()
            except httpx.ConnectError:
                return "Error: Cannot connect to sandbox manager. Is the sandbox manager running?"
            except Exception as e:
                return f"Error: Sandbox execution failed: {sanitize_mcp_error(str(e))}"

        # Log to audit
        async with _store_session() as store:
            await store.append_audit(
                AuditEntry(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    event_type="execute",
                    metadata={
                        "code_preview": code[:200],
                        "success": data.get("success", False),
                        "execution_ms": data.get("execution_ms"),
                        "restore_ms": data.get("restore_ms"),
                    },
                )
            )

        if data.get("success"):
            output = data.get("output", "").strip()
            meta = []
            if data.get("restore_ms"):
                meta.append(f"restore={data['restore_ms']:.0f}ms")
            if data.get("execution_ms"):
                meta.append(f"total={data['execution_ms']:.0f}ms")
            suffix = f"\n[{', '.join(meta)}]" if meta else ""
            return output + suffix if output else f"(no output){suffix}"
        error = data.get("error", "Unknown error")
        return f"Error:\n{sanitize_mcp_error(str(error))}"

    @audited_tool(mcp)
    async def sandbox_status() -> str:
        """
        Check the health of the sandbox manager and list active sandboxes.

        Returns sandbox manager health and active sandbox count.
        """
        async with _store_session() as store:
            settings = await store.load_settings()
        sandbox_url = settings.sandbox_manager_url

        try:
            _sandbox_headers: dict[str, str] = {}
            _sandbox_token = _os.environ.get("SP_SANDBOX_TOKEN", "")
            if _sandbox_token:
                _sandbox_headers["X-Sandbox-Auth"] = _sandbox_token
            async with httpx.AsyncClient(timeout=5, headers=_sandbox_headers) as client:
                resp = await client.get(f"{sandbox_url}/health")
                health = resp.json()
        except Exception:
            return "Sandbox manager: OFFLINE (connection failed)"

        lines = [
            "Sandbox Manager: connected",
            f"Status: {health.get('status', 'unknown')}",
            f"Active Sandboxes: {health.get('active_vms', 0)} / {health.get('max_vms', 10)}",
        ]

        org_id = mcp_org_id_var.get(None) or ""
        sandboxes = list_sandboxes(org_id)
        if sandboxes:
            lines.append(f"\nActive sandboxes: {len(sandboxes)}")
            for s in sandboxes:
                lines.append(f"  - {s.label or s.id[:8]} ({s.status})")

        return "\n".join(lines)
