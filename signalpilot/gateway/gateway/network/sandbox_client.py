"""
Sandbox Client -- BYOS (Bring Your Own Sandbox) abstraction.

Talks to the sandbox_manager HTTP API (sp-sandbox/sandbox_manager.py).
The URL is configurable from the settings page, enabling BYOS deployments.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

import httpx

from ..models import ExecuteResult, SandboxInfo

logger = logging.getLogger(__name__)


class SandboxClient:
    """HTTP client for the gVisor sandbox manager."""

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
        sandbox_token = os.environ.get("SP_SANDBOX_TOKEN", "")
        if sandbox_token:
            headers["X-Sandbox-Auth"] = sandbox_token
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
        Create a new gVisor sandbox and return a SandboxInfo.
        We create the sandbox lazily — on first execute call — to avoid the overhead
        of starting a sandbox that may never run code.
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

    async def browse_files(self, path: str | None = None, pattern: str = "*.duckdb") -> dict:
        """Browse host filesystem via sandbox manager."""
        params: dict[str, str] = {"pattern": pattern}
        if path:
            params["path"] = path
        try:
            resp = await self._client.get("/files", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Sandbox browse_files error: %s", e)
            return {"error": "Sandbox communication error", "files": [], "directories": []}

    async def execute(
        self,
        sandbox: SandboxInfo,
        code: str,
        session_token: str,
        timeout: int = 30,
        file_mounts: list[dict] | None = None,
        request_id: str | None = None,
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
            if file_mounts:
                payload["file_mounts"] = file_mounts

            extra_headers: dict[str, str] = {}
            if request_id is not None:
                extra_headers["X-Request-ID"] = request_id

            resp = await self._client.post(
                "/execute",
                json=payload,
                headers=extra_headers,
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
                    "Check your sandbox settings or ensure the sandbox manager is running."
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

    async def execute_code_with_mounts(
        self,
        code: str,
        file_mounts: list[dict],
        timeout: int = 30,
        request_id: str | None = None,
    ) -> ExecuteResult:
        """Execute code with file mounts, without needing a sandbox object."""
        start = time.monotonic()
        session_token = str(uuid.uuid4())
        try:
            payload = {
                "code": code,
                "session_token": session_token,
                "timeout": timeout,
                "file_mounts": file_mounts,
            }
            extra_headers: dict[str, str] = {}
            if request_id is not None:
                extra_headers["X-Request-ID"] = request_id

            resp = await self._client.post(
                "/execute",
                json=payload,
                headers=extra_headers,
                timeout=timeout + 10,
            )
            resp.raise_for_status()
            data = resp.json()
            return ExecuteResult(
                success=data.get("success", True),
                output=data.get("output", ""),
                error=data.get("error"),
                execution_ms=(time.monotonic() - start) * 1000,
                vm_id=data.get("vm_id"),
            )
        except Exception as e:
            logger.error("execute_code_with_mounts failed: %s", e)
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

    # ─── Kernel session methods ────────────────────────────────────────────

    async def create_kernel_session(
        self,
        session_token: str,
        gateway_url: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        payload: dict = {"session_token": session_token}
        if gateway_url:
            payload["gateway_url"] = gateway_url
        if session_id:
            payload["session_id"] = session_id
        resp = await self._client.post("/sessions", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def execute_in_session(
        self,
        session_id: str,
        code: str,
        timeout: int = 30,
        cell_id: str | None = None,
    ) -> dict:
        payload: dict = {"code": code, "timeout": timeout}
        if cell_id:
            payload["cell_id"] = cell_id
        resp = await self._client.post(
            f"/sessions/{session_id}/execute",
            json=payload,
            timeout=timeout + 10,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_kernel_session(self, session_id: str) -> dict:
        resp = await self._client.get(f"/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_session_history(self, session_id: str) -> dict:
        resp = await self._client.get(f"/sessions/{session_id}/history")
        resp.raise_for_status()
        return resp.json()

    async def delete_kernel_session(self, session_id: str) -> bool:
        resp = await self._client.delete(f"/sessions/{session_id}")
        return resp.status_code == 200

    async def restart_kernel_session(
        self,
        session_id: str,
        session_token: str | None = None,
        gateway_url: str | None = None,
    ) -> dict:
        payload: dict = {}
        if session_token:
            payload["session_token"] = session_token
        if gateway_url:
            payload["gateway_url"] = gateway_url
        resp = await self._client.post(
            f"/sessions/{session_id}/restart",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def complete_in_session(
        self, session_id: str, code: str, cursor_pos: int,
    ) -> dict:
        resp = await self._client.post(
            f"/sessions/{session_id}/complete",
            json={"code": code, "cursor_pos": cursor_pos},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def inspect_in_session(
        self, session_id: str, code: str, cursor_pos: int, detail_level: int = 0,
    ) -> dict:
        resp = await self._client.post(
            f"/sessions/{session_id}/inspect",
            json={"code": code, "cursor_pos": cursor_pos, "detail_level": detail_level},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def interrupt_session(self, session_id: str) -> bool:
        resp = await self._client.post(f"/sessions/{session_id}/interrupt")
        return resp.status_code == 200

    async def list_kernel_sessions(self) -> list[dict]:
        resp = await self._client.get("/sessions")
        resp.raise_for_status()
        return resp.json().get("sessions", [])

    async def close(self):
        await self._client.aclose()
