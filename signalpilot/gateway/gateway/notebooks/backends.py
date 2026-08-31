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
# This path exists only inside the isolated notebook sandbox.
_TOKEN_FILE = "/tmp/sp-notebook-token"  # nosec B108
# Tight poll: the exec round trip itself takes ~300ms, and a cold server
# boots in ~2s — a 2s sleep added up to 2s of pure wait to every launch.
_HEALTH_POLL_SECONDS = 0.5


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

    async def resume(self, runtime_handle: str, request: LaunchRequest) -> str:
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

    async def resume(self, runtime_handle: str, request: LaunchRequest) -> str:
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
        hydrate = 'curl -fsSL "$SP_SNAPSHOT_URL" | tar xz -C /workspace && '
    return (
        "set -e; "
        # The custom notebook image runs as its unprivileged user with
        # /workspace already writable and no sudo installed; only fall back
        # to sudo for stock sandbox images where /workspace needs root.
        '{ mkdir -p /workspace && test -w /workspace ; } 2>/dev/null '
        '|| { sudo mkdir -p /workspace && sudo chown "$(id -u):$(id -g)" /workspace; }; '
        f"{hydrate}"
        # Stage the auth token from the process env (the env is process-only,
        # never the sandbox creation spec) — avoids a provider write_file
        # round trip on the launch critical path.
        f'printf %s "$SP_NOTEBOOK_TOKEN" > {shlex.quote(_TOKEN_FILE)}; '
        "unset SP_NOTEBOOK_TOKEN; "
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

    @staticmethod
    def _process_env(request: LaunchRequest) -> dict[str, str]:
        from gateway.auth.jwt_secret import load_session_jwt_secret

        process_env = {
            **request.env,
            "SP_NOTEBOOK_TOKEN": request.notebook_token,
            "SP_SESSION_JWT": request.session_jwt,
            "SP_SESSION_JWT_SECRET": load_session_jwt_secret(),
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
        return process_env

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
            process_env = self._process_env(request)
            await self._attach_retry(
                lambda: self._runtime.start_process(
                    sandbox_id, _boot_command(request), env=process_env
                )
            )
            # The public route exists as soon as the sandbox does — resolve it
            # concurrently with the health wait instead of after it.
            routes_task = asyncio.ensure_future(
                self._attach_retry(lambda: self._route_url(sandbox_id))
            )
            try:
                await self._wait_healthy(sandbox_id, not_found_grace_seconds=30.0)
                upstream = await routes_task
            except BaseException:
                routes_task.cancel()
                raise
        except BaseException:
            # Includes cancellation from the orchestration-level launch
            # deadline. Once a handle exists we must destroy it before the
            # cancellation escapes, otherwise the UI can fail while compute
            # continues running invisibly.
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

    # The server mounts under --base-url /notebook/<session_id>, so the root
    # /health path 404s. Only the launching code knows the session id (resume
    # and is_alive have just the runtime handle), so probe path-agnostically:
    # curl without -f exits 0 for ANY HTTP response (the notebook server is
    # the only listener on the port) and non-zero when nothing listens yet.
    _HEALTH_PROBE = (
        f"curl -s -o /dev/null --max-time 2 http://localhost:{NOTEBOOK_PORT}/"
    )

    @staticmethod
    def _health_wait_script(wait_seconds: float) -> str:
        """One exec that waits IN-SANDBOX until the server answers.

        Each provider exec costs a full API round trip (~300-700ms), so
        polling from the gateway paid (round trip + sleep) per probe. This
        loops locally at 250ms granularity and returns once — the whole wait
        is a single journey.
        """
        iterations = max(1, int(wait_seconds * 4))
        return (
            f"i=0; while [ $i -lt {iterations} ]; do "
            f"curl -s -o /dev/null --max-time 2 http://localhost:{NOTEBOOK_PORT}/ && exit 0; "
            "sleep 0.25; i=$((i+1)); done; exit 1"
        )

    async def _wait_healthy(
        self,
        sandbox_id: str,
        *,
        timeout_seconds: float | None = None,
        not_found_grace_seconds: float = 0.0,
    ) -> None:
        """Poll in-sandbox /health until healthy or the deadline passes.

        not_found_grace_seconds: how long a SandboxNotFound from the attach
        is tolerated before propagating. Vercel's name lookup can lag sandbox
        creation by a few seconds, so a fresh launch needs a grace window —
        but past it (or on a resume) a 404 means the sandbox is GONE, and
        failing fast beats burning the whole health window.
        """
        start = time.monotonic()
        deadline = start + (timeout_seconds or self._settings.start_timeout_seconds)
        last_error = ""
        while time.monotonic() < deadline:
            # One in-sandbox waiter per chunk: a single provider round trip
            # covers up to 45s of 250ms-granularity local polling.
            chunk = min(45.0, max(1.0, deadline - time.monotonic()))
            try:
                result = await self._runtime.exec(
                    sandbox_id,
                    self._health_wait_script(chunk),
                    timeout_seconds=chunk + 15,
                )
            except SandboxNotFound:
                if time.monotonic() - start < not_found_grace_seconds:
                    await asyncio.sleep(_HEALTH_POLL_SECONDS)
                    continue
                raise
            if result.ok:
                return
            last_error = (result.stderr or result.stdout or "").strip()[-500:]
        raise NotebookLaunchError(
            f"Notebook server in sandbox {sandbox_id} never became healthy: {last_error}"
        )

    async def _attach_retry(self, op, *, grace_seconds: float = 30.0):
        """Run `op`, retrying SandboxNotFound during the post-create window
        where the provider's name lookup may not see the sandbox yet."""
        start = time.monotonic()
        while True:
            try:
                return await op()
            except SandboxNotFound:
                if time.monotonic() - start >= grace_seconds:
                    raise
                await asyncio.sleep(1.0)

    async def is_alive(self, runtime_handle: str) -> bool:
        try:
            result = await self._runtime.exec(
                runtime_handle,
                self._HEALTH_PROBE,
                timeout_seconds=10,
            )
        except SandboxNotFound:
            return False
        except Exception:
            return False
        return result.ok

    async def resume(self, runtime_handle: str, request: LaunchRequest) -> str:
        # Vercel persistence restores the filesystem into a new VM session;
        # it does not restore process memory. Restart the notebook server with
        # fresh credentials before waiting for its port.
        await self._runtime.resume(runtime_handle)
        await self._runtime.start_process(
            runtime_handle,
            _boot_command(request),
            env=self._process_env(request),
        )
        routes_task = asyncio.ensure_future(self._route_url(runtime_handle))
        try:
            await self._wait_healthy(
                runtime_handle,
                timeout_seconds=min(30.0, float(self._settings.start_timeout_seconds)),
            )
            return await routes_task
        except BaseException:
            routes_task.cancel()
            raise

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
        # snapshot() stops the Vercel session. Only issue an explicit stop if
        # snapshotting failed, otherwise a second lifecycle call can race the
        # provider's snapshot finalization.
        if snapshot_id is None:
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
        # A launching sandbox is tagged before its session row carries the
        # runtime handle (the handle is only persisted once launch returns),
        # so a freshly created sandbox is indistinguishable from an orphan.
        # Grant every sandbox a grace window covering the slowest launch.
        grace_seconds = max(self._settings.start_timeout_seconds * 2, 900)
        now = time.time()
        for info in rows:
            if info.sandbox_id in keep_handles:
                continue
            if (
                info.created_at_epoch is not None
                and now - info.created_at_epoch < grace_seconds
            ):
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
