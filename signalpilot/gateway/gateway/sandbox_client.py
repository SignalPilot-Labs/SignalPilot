"""
Sandbox Client — abstraction over the sandbox manager HTTP API.

Talks to the sandbox_manager HTTP API (sandbox_manager.py),
which spawns Shuru microVM sandboxes for isolated code execution.
The URL is configurable from the settings page.
"""

from __future__ import annotations

import time
import uuid

import httpx

from .models import ExecuteResult, SandboxInfo


class SandboxClient:
    """HTTP client for the Shuru sandbox manager."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )

    async def health(self) -> dict:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def list_vms(self) -> list[dict]:
        resp = await self._client.get("/vms")
        resp.raise_for_status()
        return resp.json().get("active_vms", [])

    async def create_sandbox(
        self,
        session_token: str,
        connection_name: str | None = None,
        label: str = "",
        budget_usd: float = 10.0,
        row_limit: int = 10_000,
    ) -> SandboxInfo:
        """
        Create a new sandbox session and return a SandboxInfo.
        The actual Shuru microVM is created lazily — on first execute call —
        to avoid the overhead of booting a VM that may never run code.
        """
        sandbox_id = str(uuid.uuid4())
        return SandboxInfo(
            id=sandbox_id,
            vm_id=None,  # VM will be started on first execute
            connection_name=connection_name,
            label=label,
            status="ready",
            budget_usd=budget_usd,
            row_limit=row_limit,
        )

    async def execute(
        self,
        sandbox: SandboxInfo,
        code: str,
        session_token: str,
        timeout: int = 30,
    ) -> ExecuteResult:
        """Execute code in the sandbox's VM, booting it if needed."""
        start = time.monotonic()

        try:
            payload: dict = {
                "code": code,
                "session_token": session_token,
                "timeout": timeout,
            }
            if sandbox.vm_id:
                payload["vm_id"] = sandbox.vm_id

            resp = await self._client.post(
                "/execute",
                json=payload,
                timeout=timeout + 10,
            )
            resp.raise_for_status()
            data = resp.json()

            elapsed_ms = (time.monotonic() - start) * 1000

            # Update sandbox with VM id from response
            if "vm_id" in data and sandbox.vm_id is None:
                sandbox.vm_id = data["vm_id"]
                sandbox.status = "running"

            return ExecuteResult(
                success=data.get("success", True),
                output=data.get("output", data.get("result", "")),
                error=data.get("error"),
                execution_ms=elapsed_ms,
                vm_id=sandbox.vm_id,
            )

        except httpx.ConnectError:
            return ExecuteResult(
                success=False,
                error=(
                    f"Cannot connect to sandbox manager at {self.base_url}. "
                    "Check your settings or ensure the sandbox manager is running."
                ),
                execution_ms=(time.monotonic() - start) * 1000,
            )
        except httpx.HTTPStatusError as e:
            return ExecuteResult(
                success=False,
                error=f"Sandbox manager error: {e.response.status_code} {e.response.text}",
                execution_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ExecuteResult(
                success=False,
                error=str(e),
                execution_ms=(time.monotonic() - start) * 1000,
            )

    async def kill(self, vm_id: str) -> bool:
        try:
            resp = await self._client.delete(f"/vm/{vm_id}")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._client.aclose()
