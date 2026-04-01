"""
Firecracker Sandbox Client — BYOF (Bring Your Own Firecracker) abstraction.

Talks to the sandbox_manager HTTP API (sp-firecracker-vm/sandbox_manager.py).
The URL is configurable from the settings page, enabling BYOF deployments.
"""

from __future__ import annotations

import time
import uuid

import httpx

from .models import ExecuteResult, SandboxInfo


class SandboxClient:
    """HTTP client for the Firecracker sandbox manager."""

    ALLOWED_SCHEMES = {"http", "https"}

    def __init__(self, base_url: str, api_key: str | None = None, timeout: int = 60):
        # Validate base_url to prevent SSRF via scheme injection
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        if parsed.scheme not in self.ALLOWED_SCHEMES:
            raise ValueError(f"Invalid sandbox manager URL scheme: {parsed.scheme!r}. Must be http or https.")
        if not parsed.hostname:
            raise ValueError("Invalid sandbox manager URL: missing hostname")
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
        Spin up a new Firecracker microVM and return a SandboxInfo.
        We create the VM lazily — on first execute call — to avoid the overhead
        of booting a VM that may never run code.
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
                    "Check your BYOF settings or ensure Firecracker is running."
                ),
                execution_ms=(time.monotonic() - start) * 1000,
            )
        except httpx.HTTPStatusError as e:
            # Sanitize error: don't expose raw response body which may contain
            # internal details, stack traces, or config info
            status = e.response.status_code
            if status == 429:
                detail = "Rate limited — too many sandbox requests"
            elif status >= 500:
                detail = "Sandbox manager internal error"
            else:
                detail = f"Request rejected (HTTP {status})"
            return ExecuteResult(
                success=False,
                error=f"Sandbox error: {detail}",
                execution_ms=(time.monotonic() - start) * 1000,
            )
        except httpx.TimeoutException:
            return ExecuteResult(
                success=False,
                error=f"Sandbox execution timed out after {timeout}s",
                execution_ms=(time.monotonic() - start) * 1000,
            )
        except Exception:
            return ExecuteResult(
                success=False,
                error="Unexpected sandbox execution error",
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
