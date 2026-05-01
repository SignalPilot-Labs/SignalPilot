"""SubprocessSpawner — real subprocess-based sandbox spawner.

Implements the Spawner Protocol. Owns:
  - Child process lifecycle (asyncio.create_subprocess_exec)
  - Env construction from explicit allowlist (no os.environ.copy)
  - ProxyTokenClient.mint / revoke
  - Per-run workdir (prepare/cleanup)
  - Per-run CLAUDE.md rendering
  - EventBus stream pumping via pump_stream
  - Graceful shutdown on app stop

Dependency direction (imports only leaf modules, never routes):
  SubprocessSpawner → proxy_token_client, claude_md_renderer, workdir,
                      child_handle, stream_pump, events.bus, models, config
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workspaces_api.agent.child_handle import _ChildHandle
from workspaces_api.agent.claude_md_renderer import RunRenderContext, render_run_claude_md
from workspaces_api.agent.inference import resolve_inference_source
from workspaces_api.agent.proxy_token_client import ProxyTokenClient, ProxyTokenLease
from workspaces_api.agent.spawner import SpawnRequest
from workspaces_api.agent.stream_pump import pump_stream
from workspaces_api.agent.workdir import cleanup_run_workdir, prepare_run_workdir
from workspaces_api.errors import ProxyTokenMintFailed, SpawnFailed
from workspaces_api.events.bus import EventBus
from workspaces_api.models import Run, RunEvent
from workspaces_api.schemas import RunEventOut
from workspaces_api.states import RunState

if TYPE_CHECKING:
    from workspaces_api.config import Settings

logger = logging.getLogger(__name__)

_USER_PREFIX = "run-"
_INTERNAL_SECRET_BYTES = 32


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


class SubprocessSpawner:
    """Production spawner that boots the vendored sandbox server.py as a subprocess.

    Thread/async-safe: mutations to _children are serialized within asyncio tasks.
    """

    def __init__(
        self,
        settings: "Settings",
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        token_client: ProxyTokenClient | None,
        static_md_text: str,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._bus = bus
        self._token_client = token_client
        self._static_md_text = static_md_text
        self._children: dict[uuid.UUID, _ChildHandle] = {}

    async def spawn(self, request: SpawnRequest) -> None:
        """Execute the full spawn sequence for a run.

        Steps:
          1. Cloud-mode pre-check for missing SP_API_KEY.
          2. Resolve inference creds.
          3. Render CLAUDE.md, build workdir.
          4. Mint proxy token if connector_name present.
          5. Build child env from allowlist.
          6. exec sandbox subprocess.
          7. Register _ChildHandle with stream/watcher tasks.

        Raises:
          ProxyTokenMintFailed: pre-check or mint failure.
          SpawnFailed: subprocess exec failure or workdir setup failure.
        """
        settings = self._settings
        run_id = request.run_id

        # Step 1: Cloud pre-check
        if (
            settings.sp_deployment_mode == "cloud"
            and request.connector_name
            and not settings.sp_api_key
        ):
            raise ProxyTokenMintFailed("missing_api_key")

        # Step 2: Resolve inference creds
        bundle = resolve_inference_source(settings, requested=None)

        # Step 3: Render CLAUDE.md and build workdir
        proxy_host: str | None = None
        proxy_port: int | None = None
        if request.connector_name:
            proxy_host = settings.sp_dbt_proxy_host
            # port will come from lease; we render after mint, but we need gateway_url
            # We defer full render until after mint so we have the port.
            pass

        # Step 4: Mint token (need port before workdir for template)
        lease: ProxyTokenLease | None = None
        if request.connector_name:
            if self._token_client is None:
                raise SpawnFailed(
                    f"connector_name set but no token client available for run_id={run_id}"
                )
            lease = await self._token_client.mint(
                run_id=run_id,
                connector_name=request.connector_name,
                ttl_seconds=settings.sp_dbt_proxy_token_ttl_seconds,
            )
            proxy_port = lease.host_port

        ctx = RunRenderContext(
            run_id=run_id,
            workspace_id=request.workspace_id,
            gateway_url=settings.gateway_url or "",
            mode=settings.sp_deployment_mode,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
        )
        claude_md_text = render_run_claude_md(ctx)

        workdir: Path | None = None
        try:
            workdir = prepare_run_workdir(
                root=settings.sp_run_workdir_root,
                run_id=run_id,
                claude_md_text=claude_md_text,
                static_md_text=self._static_md_text,
            )
        except Exception as exc:
            if lease is not None and self._token_client is not None:
                await self._token_client.revoke(run_id)
            raise SpawnFailed(f"workdir setup failed: {exc}") from exc

        # Step 5: Build env from explicit allowlist
        sandbox_internal_secret = secrets.token_hex(_INTERNAL_SECRET_BYTES)
        env = _build_child_env(
            run_id=run_id,
            sandbox_internal_secret=sandbox_internal_secret,
            settings=settings,
            bundle=bundle,
            lease=lease,
        )
        logger.debug(
            "subprocess_spawner env keys run_id=%s keys=%s",
            run_id,
            sorted(env.keys()),
        )

        # Step 6: Start subprocess
        try:
            proc = await asyncio.create_subprocess_exec(
                settings.sp_sandbox_python,
                str(settings.sp_sandbox_server_path),
                env=env,
                cwd=str(workdir / "home"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            if lease is not None and self._token_client is not None:
                await self._token_client.revoke(run_id)
            cleanup_run_workdir(workdir)
            raise SpawnFailed(f"subprocess exec failed: {exc}") from exc

        # Step 7: Register handle and start background tasks
        started_at = _now_utc()

        handle = _ChildHandle(
            proc=proc,
            run_id=run_id,
            workdir=workdir,
            lease=lease,
            stdout_task=asyncio.create_task(
                pump_stream(
                    reader=proc.stdout,  # type: ignore[arg-type]
                    run_id=run_id,
                    kind="stdout",
                    session_factory=self._session_factory,
                    bus=self._bus,
                    terminate_callback=self._terminate_run,
                ),
                name=f"stdout-{run_id}",
            ),
            stderr_task=asyncio.create_task(
                pump_stream(
                    reader=proc.stderr,  # type: ignore[arg-type]
                    run_id=run_id,
                    kind="stderr",
                    session_factory=self._session_factory,
                    bus=self._bus,
                    terminate_callback=self._terminate_run,
                ),
                name=f"stderr-{run_id}",
            ),
            watcher_task=asyncio.create_task(
                asyncio.sleep(0),  # placeholder, replaced below
                name=f"watcher-placeholder-{run_id}",
            ),
            started_at=started_at,
        )

        # Replace watcher placeholder with real task now that handle exists
        handle.watcher_task.cancel()
        handle.watcher_task = asyncio.create_task(
            self._process_watcher(handle),
            name=f"watcher-{run_id}",
        )

        self._children[run_id] = handle
        logger.info(
            "subprocess_spawner spawned run_id=%s pid=%s connector=%s",
            run_id,
            proc.pid,
            request.connector_name,
        )

    async def _terminate_run(self, run_id: uuid.UUID, reason: str) -> None:
        """Look up the child handle and terminate it. Used by stream_pump callback."""
        handle = self._children.get(run_id)
        if handle is None:
            logger.warning(
                "subprocess_spawner terminate: no handle for run_id=%s reason=%s",
                run_id,
                reason,
            )
            return
        logger.info(
            "subprocess_spawner terminating run_id=%s reason=%s",
            run_id,
            reason,
        )
        await handle.terminate()

    async def _process_watcher(self, handle: _ChildHandle) -> None:
        """Watch for subprocess exit, update run state, clean up resources."""
        run_id = handle.run_id
        exit_code = await handle.proc.wait()

        # Drain remaining buffered output (best-effort, 2s timeout)
        for task in (handle.stdout_task, handle.stderr_task):
            if not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except (TimeoutError, asyncio.CancelledError, Exception):
                    task.cancel()

        # Update run state in DB
        if exit_code == 0:
            await self._mark_run_terminal(run_id, RunState.succeeded, error_code=None)
        else:
            await self._mark_run_terminal(
                run_id, RunState.failed, error_code="agent_nonzero_exit"
            )

        # Emit stream_end event
        await self._emit_stream_end(run_id)

        # Revoke lease (best-effort)
        if handle.lease is not None and self._token_client is not None:
            try:
                await self._token_client.revoke(run_id)
            except Exception as exc:
                logger.warning(
                    "subprocess_spawner lease revoke failed run_id=%s: %r",
                    run_id,
                    exc,
                )

        # Cleanup workdir
        cleanup_run_workdir(handle.workdir)

        # Remove from children map
        self._children.pop(run_id, None)
        logger.info(
            "subprocess_spawner run finished run_id=%s exit_code=%s",
            run_id,
            exit_code,
        )

    async def _mark_run_terminal(
        self,
        run_id: uuid.UUID,
        state: RunState,
        error_code: str | None,
    ) -> None:
        """Update the run row in DB to a terminal state."""
        try:
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    logger.error(
                        "subprocess_spawner watcher: run not found run_id=%s", run_id
                    )
                    return
                now = _now_utc()
                run.state = state.value
                run.updated_at = now
                run.finished_at = now

                payload: dict = {}
                if error_code:
                    payload["error_code"] = error_code
                ev = RunEvent(
                    run_id=run_id,
                    kind="run.finished",
                    payload=payload,
                )
                session.add(ev)
                await session.flush()
                await session.refresh(ev)
                await session.commit()

            await self._bus.publish(run_id, RunEventOut.model_validate(ev))
        except Exception as exc:
            logger.error(
                "subprocess_spawner _mark_run_terminal failed run_id=%s: %r",
                run_id,
                exc,
            )

    async def _emit_stream_end(self, run_id: uuid.UUID) -> None:
        """Persist a stream_end event and publish to bus."""
        try:
            async with self._session_factory() as session:
                ev = RunEvent(run_id=run_id, kind="stream_end", payload={})
                session.add(ev)
                await session.flush()
                await session.refresh(ev)
                await session.commit()

            await self._bus.publish(run_id, RunEventOut.model_validate(ev))
        except Exception as exc:
            logger.error(
                "subprocess_spawner _emit_stream_end failed run_id=%s: %r",
                run_id,
                exc,
            )

    async def shutdown(self) -> None:
        """Terminate all running children gracefully and revoke their leases."""
        if not self._children:
            return

        run_ids = list(self._children.keys())
        logger.info("subprocess_spawner shutdown: terminating %d children", len(run_ids))

        handles = [h for h in (self._children.get(rid) for rid in run_ids) if h]
        for handle in handles:
            await handle.terminate()
            if handle.lease is not None and self._token_client is not None:
                try:
                    await self._token_client.revoke(handle.run_id)
                except Exception as exc:
                    logger.warning(
                        "subprocess_spawner shutdown revoke failed run_id=%s: %r",
                        handle.run_id,
                        exc,
                    )

        # Wait for watcher tasks to complete (they update run state and clean up)
        watcher_tasks = [h.watcher_task for h in handles if not h.watcher_task.done()]
        if watcher_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*watcher_tasks, return_exceptions=True),
                    timeout=10,
                )
            except TimeoutError:
                logger.warning("subprocess_spawner shutdown: watcher tasks did not complete in time")
                for task in watcher_tasks:
                    task.cancel()


def _build_child_env(
    run_id: uuid.UUID,
    sandbox_internal_secret: str,
    settings: "Settings",
    bundle: object,
    lease: ProxyTokenLease | None,
) -> dict[str, str]:
    """Build the subprocess env from an explicit allowlist.

    No os.environ.copy(). Only the vars listed here are forwarded.
    """
    from workspaces_api.agent.inference import InferenceBundle

    assert isinstance(bundle, InferenceBundle)

    env: dict[str, str] = {}

    # Always-present vars
    env["AGENT_INTERNAL_SECRET"] = sandbox_internal_secret
    env["SP_MODE"] = settings.sp_deployment_mode
    env["SP_GATEWAY_URL"] = settings.gateway_url or ""
    env["HOME"] = str(settings.sp_run_workdir_root / str(run_id) / "home")
    env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    # Inference: exactly one of CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY
    if bundle.mode == "local" and bundle.oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = bundle.oauth_token
    elif bundle.mode == "byo" and bundle.api_key:
        env["ANTHROPIC_API_KEY"] = bundle.api_key

    # DB proxy vars — only when lease is present
    if lease is not None:
        env["PGHOST"] = settings.sp_dbt_proxy_host
        env["PGPORT"] = str(lease.host_port)
        env["PGUSER"] = f"{_USER_PREFIX}{run_id}"
        env["PGPASSWORD"] = lease.token
        env["PGSSLMODE"] = "disable"

    return env
