"""Notebook compute backends (Runtime v2).

Two backends, one seam:

- VercelNotebookBackend — a sandbox VM per session. Hydrates /workspace from a
  presigned S3 snapshot, starts the notebook server as a detached process,
  exposes :2718 through the sandbox's public route URL, and supports the full
  scale-to-zero lifecycle (extend / snapshot / resume / destroy).
- DirectNotebookBackend — the local docker-compose container at
  SP_NOTEBOOK_DIRECT_URL. No lifecycle: it is always "on".

The gateway proxy composes the upstream as `{upstream_url}/notebook/{sid}` for
vercel sessions (the server runs with --base-url) and uses the direct URL
verbatim locally (the compose server runs without one).
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..config.notebooks import NotebookSettings, get_notebook_settings
from ..runtime.mode import is_cloud_mode
from ..sandbox_runtime import SandboxRuntime, SandboxSpec, get_sandbox_runtime
from ..sandbox_runtime.base import SandboxNotFound

logger = logging.getLogger(__name__)

NOTEBOOK_PORT = 2718
NOTEBOOK_SANDBOX_TAG = {"sp-purpose": "notebook"}
_TOKEN_FILE = "/tmp/sp-notebook-token"
_HEALTH_POLL_SECONDS = 2.0


class NotebookLaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class LaunchRequest:
    org_id: str
    user_id: str
    session_id: str
    project_id: str | None
    branch: str
    session_jwt: str
    notebook_token: str
    env: dict[str, str] = field(default_factory=dict)
    snapshot_url: str | None = None
    base_revision: int | None = None
    read_only: bool = False


@dataclass(frozen=True)
class NotebookLaunch:
    runtime_handle: str
    upstream_url: str


class NotebookBackend(Protocol):
    name: str

    async def launch(self, request: LaunchRequest) -> NotebookLaunch: ...

    async def is_alive(self, runtime_handle: str) -> bool: ...

    async def resume(self, runtime_handle: str) -> str:
        """Resume a snapshotted session; returns the (possibly new) upstream URL."""
        ...

    async def snapshot_and_stop(self, runtime_handle: str) -> str | None:
        """Snapshot then release compute. Returns the snapshot id, or None
        when the backend has nothing to snapshot."""
        ...

    async def extend(self, runtime_handle: str, seconds: int) -> None: ...

    async def terminate(self, runtime_handle: str) -> None: ...


# ── Direct (local compose) ───────────────────────────────────────────────────


class DirectNotebookBackend:
    """One shared always-on notebook container. Lifecycle is docker-compose's
    problem; every method degrades to the obvious no-op."""

    name = "direct"

    def __init__(self, direct_url: str) -> None:
        self._direct_url = direct_url.rstrip("/")

    async def launch(self, request: LaunchRequest) -> NotebookLaunch:
        return NotebookLaunch(runtime_handle="local-notebook", upstream_url=self._direct_url)

    async def is_alive(self, runtime_handle: str) -> bool:
        return True

    async def resume(self, runtime_handle: str) -> str:
        return self._direct_url

    async def snapshot_and_stop(self, runtime_handle: str) -> str | None:
        return None

    async def extend(self, runtime_handle: str, seconds: int) -> None:
        return None

    async def terminate(self, runtime_handle: str) -> None:
        return None


# ── Vercel Sandbox ───────────────────────────────────────────────────────────


def _boot_command(request: LaunchRequest) -> str:
    """The in-sandbox boot: prepare /workspace, hydrate it from the snapshot,
    stage the auth token file, then run the notebook server bound to :2718.

    The image is expected to ship the `sp` CLI (the signalpilot notebook
    server); everything else is stock-sandbox-safe shell.
    """
    hydrate = ""
    if request.snapshot_url:
        hydrate = f'curl -fsSL "$SP_SNAPSHOT_URL" | tar xz -C /workspace && '
    return (
        "set -e; "
        'sudo mkdir -p /workspace && sudo chown "$(id -u):$(id -g)" /workspace; '
        f"{hydrate}"
        f"chmod 0400 {shlex.quote(_TOKEN_FILE)}; "
        "exec sp edit --host 0.0.0.0 --port 2718 --headless "
        f"--token-password-file {shlex.quote(_TOKEN_FILE)} "
        "--no-skew-protection "
        '--base-url "/notebook/$SP_SESSION_ID" /workspace'
    )


class VercelNotebookBackend:
    name = "vercel"

    def __init__(
        self,
        settings: NotebookSettings | None = None,
        *,
        runtime: SandboxRuntime | None = None,
    ) -> None:
        self._settings = settings or get_notebook_settings()
        self._runtime = runtime or get_sandbox_runtime()

    async def launch(self, request: LaunchRequest) -> NotebookLaunch:
        settings = self._settings
        image = settings.require_vercel_image(cloud=is_cloud_mode())
        grant = min(settings.session_grant_seconds, 2700)
        spec = SandboxSpec(
            time_limit_seconds=grant,
            image=image,
            ports=(NOTEBOOK_PORT,),
            vcpus=settings.vcpus,
            memory_mb=settings.memory_mb,
            egress_allow_hosts=settings.egress_allow or None,
            tags={
                **NOTEBOOK_SANDBOX_TAG,
                "sp-org": request.org_id[:64],
                "sp-session": request.session_id[:64],
            },
            # Creation metadata is readable back from the provider API, so no
            # secrets ride the spec env — they go to the boot process only.
            env={},
        )
        sandbox_id = await self._runtime.create(spec)
        try:
            await self._runtime.write_file(
                sandbox_id, _TOKEN_FILE, request.notebook_token.encode("utf-8")
            )
            process_env = {
                **request.env,
                "SP_SESSION_JWT": request.session_jwt,
                "SP_SESSION_ID": request.session_id,
                "SP_ORG_ID": request.org_id,
                "SP_USER_ID": request.user_id,
                "SP_BRANCH": request.branch,
                "SP_WORKSPACE_MODE": "s3",
            }
            if request.project_id:
                process_env["SP_PROJECT_ID"] = request.project_id
            if request.snapshot_url:
                process_env["SP_SNAPSHOT_URL"] = request.snapshot_url
            if request.base_revision is not None:
                process_env["SP_WORKSPACE_BASE_REVISION"] = str(request.base_revision)
            if request.read_only:
                process_env["SP_PROJECT_READ_ONLY"] = "1"
            await self._runtime.start_process(
                sandbox_id, _boot_command(request), env=process_env
            )
            await self._wait_healthy(sandbox_id)
            upstream = await self._route_url(sandbox_id)
        except Exception:
            await self._runtime.destroy(sandbox_id)
            raise
        return NotebookLaunch(runtime_handle=sandbox_id, upstream_url=upstream)

    async def _route_url(self, sandbox_id: str) -> str:
        routes = await self._runtime.routes(sandbox_id)
        upstream = routes.get(NOTEBOOK_PORT)
        if not upstream:
            raise NotebookLaunchError(
                f"Sandbox {sandbox_id} exposes no route for port {NOTEBOOK_PORT}"
            )
        return upstream.rstrip("/")

    async def _wait_healthy(self, sandbox_id: str) -> None:
        deadline = time.monotonic() + self._settings.start_timeout_seconds
        last_error = ""
        while time.monotonic() < deadline:
            result = await self._runtime.exec(
                sandbox_id,
                f"curl -sf --max-time 2 http://localhost:{NOTEBOOK_PORT}/health",
                timeout_seconds=10,
            )
            if result.ok:
                return
            last_error = (result.stderr or result.stdout or "").strip()[-500:]
            await asyncio.sleep(_HEALTH_POLL_SECONDS)
        raise NotebookLaunchError(
            f"Notebook server in sandbox {sandbox_id} never became healthy: {last_error}"
        )

    async def is_alive(self, runtime_handle: str) -> bool:
        try:
            result = await self._runtime.exec(
                runtime_handle,
                f"curl -sf --max-time 2 http://localhost:{NOTEBOOK_PORT}/health",
                timeout_seconds=10,
            )
        except SandboxNotFound:
            return False
        except Exception:
            return False
        return result.ok

    async def resume(self, runtime_handle: str) -> str:
        await self._runtime.resume(runtime_handle)
        await self._wait_healthy(runtime_handle)
        return await self._route_url(runtime_handle)

    async def snapshot_and_stop(self, runtime_handle: str) -> str | None:
        try:
            snapshot_id = await self._runtime.snapshot(
                runtime_handle,
                expiration_seconds=self._settings.snapshot_expiration_seconds,
            )
        except SandboxNotFound:
            return None
        except Exception:
            logger.warning("Snapshot failed for %s; destroying without one", runtime_handle)
            snapshot_id = None
        await self._runtime.stop(runtime_handle)
        return snapshot_id

    async def extend(self, runtime_handle: str, seconds: int) -> None:
        await self._runtime.extend_time_limit(runtime_handle, seconds)

    async def terminate(self, runtime_handle: str) -> None:
        await self._runtime.destroy(runtime_handle)

    async def reap_orphans(self, keep_handles: set[str]) -> int:
        """Destroy notebook-tagged sandboxes no live session row owns —
        the crashed-gateway backstop."""
        reaped = 0
        try:
            rows = await self._runtime.list(tags=dict(NOTEBOOK_SANDBOX_TAG))
        except Exception:
            logger.warning("Notebook sandbox inventory failed; skipping reap", exc_info=True)
            return 0
        for info in rows:
            if info.sandbox_id in keep_handles:
                continue
            try:
                await self._runtime.destroy(info.sandbox_id)
                reaped += 1
                logger.info("Reaped orphan notebook sandbox %s", info.sandbox_id)
            except Exception:
                logger.warning("Could not reap sandbox %s", info.sandbox_id, exc_info=True)
        return reaped


def get_notebook_backend(settings: NotebookSettings | None = None) -> NotebookBackend:
    settings = settings or get_notebook_settings()
    backend = settings.resolved_backend()
    if backend == "direct":
        if not settings.direct_url:
            raise NotebookLaunchError("SP_NOTEBOOK_DIRECT_URL is required for the direct backend")
        return DirectNotebookBackend(settings.direct_url)
    if backend == "vercel":
        return VercelNotebookBackend(settings)
    raise NotebookLaunchError(f"Unknown notebook backend: {backend}")
