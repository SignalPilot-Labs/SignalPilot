"""Vercel Sandbox implementation of the sandbox runtime interface.

Uses the sync API of the `vercel` SDK (v0.9+) off the event loop via
asyncio.to_thread. The SDK authenticates through the process environment
(VERCEL_TOKEN / VERCEL_TEAM_ID / VERCEL_PROJECT_ID); values are validated by
`gateway.config.sandbox_runtime` before this runtime is handed out.

Sandboxes are reattached by name on every call (`get_sandbox`), so no
in-process state survives between calls and any worker can drive, snapshot,
or destroy any sandbox.
"""

from __future__ import annotations

import asyncio
import logging
import posixpath
from typing import Any

from gateway.sandbox_runtime.base import (
    ExecResult,
    GitCheckout,
    SandboxInfo,
    SandboxNotFound,
    SandboxRuntimeError,
    SandboxSpec,
)

logger = logging.getLogger(__name__)
_IMAGE_READY_RETRY_DELAYS_SECONDS = (5.0, 15.0)


def _image_is_not_ready(exc: Exception) -> bool:
    """VCR can acknowledge a push before Sandbox can launch its digest."""
    return "image_not_ready" in str(exc).lower()


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


def _resources(spec: SandboxSpec) -> Any | None:
    if spec.vcpus is None and spec.memory_mb is None:
        return None
    from vercel.sandbox import SandboxResources

    return SandboxResources(vcpus=spec.vcpus, memory=spec.memory_mb)


def _network_policy(spec: SandboxSpec) -> Any | None:
    """Map the provider-agnostic egress allowlist onto the SDK policy.

    None keeps the provider default; an empty tuple denies all egress; a
    non-empty tuple allows exactly those domains with pass-through rules.
    """
    if spec.egress_allow_hosts is None:
        return None
    from vercel.sandbox import NetworkPolicy, NetworkPolicyRule

    if not spec.egress_allow_hosts:
        return NetworkPolicy.deny_all()
    return NetworkPolicy.custom(
        {host: [NetworkPolicyRule()] for host in spec.egress_allow_hosts}
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
            image=spec.image,
            source=_git_source(spec.git) if spec.git else None,
            ports=list(spec.ports) or None,
            execution_time_limit=spec.time_limit_seconds,
            resources=_resources(spec),
            persistent=spec.persistent or None,
            network_policy=_network_policy(spec),
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

    def _start_process_sync(
        self, sandbox_id: str, command: str, cwd: str | None, env: dict[str, str] | None
    ) -> str:
        import subprocess

        sandbox = self._attach_sync(sandbox_id)
        process = sandbox.create_process(
            "bash",
            ["-c", command],
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return str(process.id)

    def _routes_sync(self, sandbox_id: str) -> dict[int, str]:
        sandbox = self._attach_sync(sandbox_id)
        return {int(route.port): str(route.url) for route in (sandbox.routes or ())}

    def _extend_sync(self, sandbox_id: str, seconds: int) -> None:
        sandbox = self._attach_sync(sandbox_id)
        sandbox.extend_execution_time_limit(max(1, int(seconds)))

    def _snapshot_sync(self, sandbox_id: str, expiration_seconds: int | None) -> str:
        sandbox = self._attach_sync(sandbox_id)
        snapshot = sandbox.snapshot(expiration=expiration_seconds)
        return str(snapshot.id)

    def _resume_sync(self, sandbox_id: str) -> None:
        sdk = _sdk()
        try:
            handle = sdk.resume_sandbox(name=sandbox_id, project_id=self._project_id)
        except Exception as exc:
            raise SandboxNotFound(f"Sandbox {sandbox_id} cannot be resumed") from exc
        # Entering waits for readiness; the handle is deliberately never
        # exited — lifecycle stays with the caller, as in create().
        enter = getattr(handle, "__enter__", None)
        if callable(enter):
            enter()

    def _stop_sync(self, sandbox_id: str) -> None:
        try:
            sandbox = self._attach_sync(sandbox_id)
        except SandboxNotFound:
            return
        try:
            sandbox.stop()
        except Exception:
            return

    def _list_sync(self, tags: dict[str, str] | None) -> list[SandboxInfo]:
        sdk = _sdk()
        rows: list[SandboxInfo] = []
        for sandbox in sdk.query_sandboxes(project_id=self._project_id):
            sandbox_tags = dict(sandbox.tags or {})
            if tags and any(sandbox_tags.get(key) != value for key, value in tags.items()):
                continue
            created_at = getattr(sandbox, "created_at", None)
            created_at_epoch: float | None = None
            if isinstance(created_at, (int, float)) and created_at > 0:
                # The API reports epoch milliseconds.
                created_at_epoch = (
                    created_at / 1000.0 if created_at > 1e12 else float(created_at)
                )
            rows.append(
                SandboxInfo(
                    sandbox_id=str(sandbox.name),
                    status=str(sandbox.status or "unknown"),
                    tags=sandbox_tags,
                    snapshot_id=getattr(sandbox, "current_snapshot_id", None),
                    created_at_epoch=created_at_epoch,
                )
            )
        return rows

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
        for attempt in range(len(_IMAGE_READY_RETRY_DELAYS_SECONDS) + 1):
            try:
                return await asyncio.to_thread(self._create_sync, spec)
            except Exception as exc:
                if (
                    not _image_is_not_ready(exc)
                    or attempt >= len(_IMAGE_READY_RETRY_DELAYS_SECONDS)
                ):
                    raise
                delay = _IMAGE_READY_RETRY_DELAYS_SECONDS[attempt]
                logger.warning(
                    "Vercel sandbox image is not ready; retrying create in %.0fs "
                    "(attempt %d/%d)",
                    delay,
                    attempt + 2,
                    len(_IMAGE_READY_RETRY_DELAYS_SECONDS) + 1,
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

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

    async def start_process(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        return await asyncio.to_thread(self._start_process_sync, sandbox_id, command, cwd, env)

    async def routes(self, sandbox_id: str) -> dict[int, str]:
        return await asyncio.to_thread(self._routes_sync, sandbox_id)

    async def extend_time_limit(self, sandbox_id: str, seconds: int) -> None:
        await asyncio.to_thread(self._extend_sync, sandbox_id, seconds)

    async def snapshot(self, sandbox_id: str, *, expiration_seconds: int | None = None) -> str:
        return await asyncio.to_thread(self._snapshot_sync, sandbox_id, expiration_seconds)

    async def resume(self, sandbox_id: str) -> None:
        await asyncio.to_thread(self._resume_sync, sandbox_id)

    async def stop(self, sandbox_id: str) -> None:
        await asyncio.to_thread(self._stop_sync, sandbox_id)

    async def list(self, *, tags: dict[str, str] | None = None) -> list[SandboxInfo]:
        return await asyncio.to_thread(self._list_sync, tags)

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> None:
        await asyncio.to_thread(self._write_sync, sandbox_id, path, content)

    async def read_file(self, sandbox_id: str, path: str) -> bytes | None:
        return await asyncio.to_thread(self._read_sync, sandbox_id, path)

    async def destroy(self, sandbox_id: str) -> None:
        await asyncio.to_thread(self._destroy_sync, sandbox_id)
