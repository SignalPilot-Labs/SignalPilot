"""Vercel Sandbox implementation of the sandbox runtime interface.

Uses the sync API of the `vercel` SDK (v0.9+) off the event loop via
asyncio.to_thread. The SDK authenticates through the process environment
(VERCEL_TOKEN / VERCEL_TEAM_ID / VERCEL_PROJECT_ID); values are validated by
`gateway.config.sandbox_runtime` before this runtime is handed out.

Sandboxes are reattached by id on every call (`get_sandbox`), so no in-process
state survives between calls and any worker can drive or destroy any sandbox.
"""

from __future__ import annotations

import asyncio
import posixpath
from typing import Any

from gateway.sandbox_runtime.base import (
    ExecResult,
    GitCheckout,
    SandboxNotFound,
    SandboxRuntimeError,
    SandboxSpec,
)


def _sdk() -> Any:
    """Import the SDK lazily so unit tests can run without it installed."""
    try:
        from vercel.sandbox import sync as vercel_sync
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SandboxRuntimeError("The 'vercel' package is not installed") from exc
    return vercel_sync


def _git_source(git: GitCheckout) -> Any:
    from vercel.sandbox import GitSource

    return GitSource(
        type="git",
        url=git.url,
        revision=git.revision,
        depth=git.depth,
        username=git.username,
        password=git.password,
    )


class VercelSandboxRuntime:
    provider = "vercel"

    def __init__(self, *, project_id: str | None = None) -> None:
        self._project_id = project_id

    # -- internals -----------------------------------------------------------

    def _create_sync(self, spec: SandboxSpec) -> str:
        sdk = _sdk()
        operation = sdk.create_sandbox(
            project_id=self._project_id,
            source=_git_source(spec.git) if spec.git else None,
            execution_time_limit=spec.time_limit_seconds,
            env=spec.env or None,
            tags=spec.tags or None,
            destroy=False,
        )
        sandbox = operation.__enter__()
        # The v0.9 SDK identifies sandboxes by their unique generated name.
        return str(sandbox.name)

    def _attach_sync(self, sandbox_id: str) -> Any:
        sdk = _sdk()
        try:
            return sdk.get_sandbox(name=sandbox_id, project_id=self._project_id)
        except Exception as exc:
            raise SandboxNotFound(f"Sandbox {sandbox_id} is not reachable") from exc

    def _exec_sync(
        self,
        sandbox_id: str,
        command: str,
        cwd: str | None,
        env: dict[str, str] | None,
        timeout_seconds: float | None,
    ) -> ExecResult:
        sandbox = self._attach_sync(sandbox_id)
        result = sandbox.run_process(
            "bash",
            ["-c", command],
            cwd=cwd,
            env=env,
            kill_after=timeout_seconds,
            capture_output=True,
        )
        return ExecResult(
            returncode=int(result.returncode),
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
        )

    def _write_sync(self, sandbox_id: str, path: str, content: bytes) -> None:
        sandbox = self._attach_sync(sandbox_id)
        parent = posixpath.dirname(path)
        if parent and parent != "/" and not sandbox.fs.exists(parent):
            sandbox.fs.mkdir(parent)
        sandbox.fs.write_bytes(path, content)

    def _read_sync(self, sandbox_id: str, path: str) -> bytes | None:
        sandbox = self._attach_sync(sandbox_id)
        if not sandbox.fs.exists(path):
            return None
        data = sandbox.fs.read_bytes(path)
        return bytes(data) if data is not None else None

    def _destroy_sync(self, sandbox_id: str) -> None:
        try:
            sandbox = self._attach_sync(sandbox_id)
        except SandboxNotFound:
            return
        try:
            sandbox.destroy()
        except Exception:
            # Destroy must be safe to call from cleanup paths; the provider's
            # execution time limit is the backstop for anything we miss.
            return

    # -- SandboxRuntime ------------------------------------------------------

    async def create(self, spec: SandboxSpec) -> str:
        return await asyncio.to_thread(self._create_sync, spec)

    async def exec(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecResult:
        return await asyncio.to_thread(self._exec_sync, sandbox_id, command, cwd, env, timeout_seconds)

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> None:
        await asyncio.to_thread(self._write_sync, sandbox_id, path, content)

    async def read_file(self, sandbox_id: str, path: str) -> bytes | None:
        return await asyncio.to_thread(self._read_sync, sandbox_id, path)

    async def destroy(self, sandbox_id: str) -> None:
        await asyncio.to_thread(self._destroy_sync, sandbox_id)
