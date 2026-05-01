"""Tests for SubprocessSpawner using fake_sandbox.py."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workspaces_api.agent.inference import InferenceBundle
from workspaces_api.agent.proxy_token_client import ProxyTokenClient, ProxyTokenLease
from workspaces_api.agent.spawner import SpawnRequest
from workspaces_api.agent.subprocess_spawner import SubprocessSpawner
from workspaces_api.config import Settings
from workspaces_api.errors import ProxyTokenMintFailed
from workspaces_api.events.bus import EventBus
from workspaces_api.models import Run
from workspaces_api.states import RunState

_FAKE_SANDBOX = Path(__file__).parent / "fixtures" / "fake_sandbox.py"
_NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _local_settings(tmp_path: Path) -> Settings:
    return Settings.model_validate({
        "SP_DEPLOYMENT_MODE": "local",
        "CLAUDE_CODE_OAUTH_TOKEN": "test-oauth-token",
        "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "SP_SANDBOX_SERVER_PATH": str(_FAKE_SANDBOX),
        "SP_RUN_WORKDIR_ROOT": str(tmp_path / "runs"),
        "SP_USE_SUBPROCESS_SPAWNER": "true",
        "SP_GATEWAY_URL": "http://gateway.test:3100",
    })


def _cloud_settings(tmp_path: Path, api_key: str | None = "sp_testkey") -> Settings:
    kwargs: dict = {
        "SP_DEPLOYMENT_MODE": "cloud",
        "ANTHROPIC_API_KEY": "sk-ant-testkey",
        "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "SP_SANDBOX_SERVER_PATH": str(_FAKE_SANDBOX),
        "SP_RUN_WORKDIR_ROOT": str(tmp_path / "runs"),
        "SP_USE_SUBPROCESS_SPAWNER": "true",
        "SP_GATEWAY_URL": "http://gateway.test:3100",
    }
    if api_key:
        kwargs["SP_API_KEY"] = api_key
    return Settings.model_validate({**kwargs})


def _make_spawn_request(
    run_id: uuid.UUID,
    connector_name: str | None = None,
    mode: str = "local",
) -> SpawnRequest:
    if mode == "local":
        bundle = InferenceBundle(
            mode="local", oauth_token="test-oauth-token", api_key=None, base_url=None
        )
    else:
        bundle = InferenceBundle(
            mode="byo", oauth_token=None, api_key="sk-ant-testkey", base_url=None
        )
    return SpawnRequest(
        run_id=run_id,
        workspace_id="ws-test",
        prompt="test prompt",
        inference=bundle,
        gateway_run_token=None,
        dbt_proxy_host_port=None,
        connector_name=connector_name,
        sandbox_internal_secret="deadbeef" * 8,
    )


def _make_mock_token_client(
    lease: ProxyTokenLease | None = None,
    raise_on_mint: Exception | None = None,
) -> MagicMock:
    client = MagicMock(spec=ProxyTokenClient)
    if raise_on_mint:
        client.mint = AsyncMock(side_effect=raise_on_mint)
    else:
        client.mint = AsyncMock(return_value=lease)
    client.revoke = AsyncMock()
    return client


def _make_default_lease() -> ProxyTokenLease:
    return ProxyTokenLease(
        token="minted-proxy-token-xyz",
        host_port=15432,
        expires_at=datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc),
    )


class TestSubprocessSpawnerEnv:
    """Verify env vars injected into child process."""

    @pytest.mark.asyncio
    async def test_env_contains_required_vars(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Child env must contain SP_MODE, SP_GATEWAY_URL, HOME, PATH, AGENT_INTERNAL_SECRET."""
        settings = _local_settings(tmp_path)
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id,
                workspace_id="ws-test",
                prompt="test",
                state=RunState.queued.value,
                inference_mode="local",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings,
            session_factory=session_factory,
            bus=bus,
            token_client=None,
            static_md_text="# static",
        )

        captured_env: dict = {}
        original_exec = asyncio.create_subprocess_exec

        async def capture_exec(*args, env=None, **kwargs):  # type: ignore[no-untyped-def]
            if env:
                captured_env.update(env)
            # Use actual args but point at fake sandbox
            return await original_exec(*args, env=env, **kwargs)

        import workspaces_api.agent.subprocess_spawner as ss_mod
        orig = ss_mod.asyncio.create_subprocess_exec
        ss_mod.asyncio.create_subprocess_exec = capture_exec  # type: ignore[attr-defined]

        try:
            req = _make_spawn_request(run_id, connector_name=None)
            await spawner.spawn(req)
            await asyncio.sleep(1.5)  # Let fake_sandbox finish
        finally:
            ss_mod.asyncio.create_subprocess_exec = orig  # type: ignore[attr-defined]
            await spawner.shutdown()

        assert "AGENT_INTERNAL_SECRET" in captured_env
        assert "SP_MODE" in captured_env
        assert captured_env["SP_MODE"] == "local"
        assert "SP_GATEWAY_URL" in captured_env
        assert "HOME" in captured_env
        assert "PATH" in captured_env
        assert "CLAUDE_CODE_OAUTH_TOKEN" in captured_env

    @pytest.mark.asyncio
    async def test_env_does_not_contain_db_url_or_host_creds(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _local_settings(tmp_path)
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id,
                workspace_id="ws-test",
                prompt="test",
                state=RunState.queued.value,
                inference_mode="local",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        captured_env: dict = {}
        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings,
            session_factory=session_factory,
            bus=bus,
            token_client=None,
            static_md_text="# static",
        )

        import workspaces_api.agent.subprocess_spawner as ss_mod
        orig = ss_mod.asyncio.create_subprocess_exec

        async def capture_exec(*args, env=None, **kwargs):  # type: ignore[no-untyped-def]
            if env:
                captured_env.update(env)
            return await orig(*args, env=env, **kwargs)

        ss_mod.asyncio.create_subprocess_exec = capture_exec  # type: ignore[attr-defined]

        try:
            req = _make_spawn_request(run_id, connector_name=None)
            await spawner.spawn(req)
            await asyncio.sleep(1.5)
        finally:
            ss_mod.asyncio.create_subprocess_exec = orig  # type: ignore[attr-defined]
            await spawner.shutdown()

        assert "WORKSPACES_DATABASE_URL" not in captured_env
        # No PG vars when no connector
        assert "PGHOST" not in captured_env
        assert "PGPASSWORD" not in captured_env

    @pytest.mark.asyncio
    async def test_no_pg_vars_when_connector_name_none(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _local_settings(tmp_path)
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id, workspace_id="ws-test", prompt="test",
                state=RunState.queued.value, inference_mode="local",
                created_at=_now(), updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        captured_env: dict = {}
        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings, session_factory=session_factory, bus=bus,
            token_client=None, static_md_text="# static",
        )

        import workspaces_api.agent.subprocess_spawner as ss_mod
        orig = ss_mod.asyncio.create_subprocess_exec

        async def capture_exec(*args, env=None, **kwargs):  # type: ignore[no-untyped-def]
            if env:
                captured_env.update(env)
            return await orig(*args, env=env, **kwargs)

        ss_mod.asyncio.create_subprocess_exec = capture_exec  # type: ignore[attr-defined]

        try:
            await spawner.spawn(_make_spawn_request(run_id, connector_name=None))
            await asyncio.sleep(1.5)
        finally:
            ss_mod.asyncio.create_subprocess_exec = orig  # type: ignore[attr-defined]
            await spawner.shutdown()

        pg_vars = {k for k in captured_env if k.startswith("PG")}
        assert pg_vars == set()

    @pytest.mark.asyncio
    async def test_pguser_format_with_connector(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _local_settings(tmp_path)
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id, workspace_id="ws-test", prompt="test",
                state=RunState.queued.value, inference_mode="local",
                created_at=_now(), updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        lease = _make_default_lease()
        token_client = _make_mock_token_client(lease=lease)
        captured_env: dict = {}
        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings, session_factory=session_factory, bus=bus,
            token_client=token_client, static_md_text="# static",
        )

        import workspaces_api.agent.subprocess_spawner as ss_mod
        orig = ss_mod.asyncio.create_subprocess_exec

        async def capture_exec(*args, env=None, **kwargs):  # type: ignore[no-untyped-def]
            if env:
                captured_env.update(env)
            return await orig(*args, env=env, **kwargs)

        ss_mod.asyncio.create_subprocess_exec = capture_exec  # type: ignore[attr-defined]

        try:
            await spawner.spawn(_make_spawn_request(run_id, connector_name="my_conn"))
            await asyncio.sleep(1.5)
        finally:
            ss_mod.asyncio.create_subprocess_exec = orig  # type: ignore[attr-defined]
            await spawner.shutdown()

        assert captured_env.get("PGUSER") == f"run-{run_id}"
        assert captured_env.get("PGPASSWORD") == "minted-proxy-token-xyz"
        assert captured_env.get("PGHOST") == "127.0.0.1"


class TestSubprocessSpawnerFailures:
    @pytest.mark.asyncio
    async def test_mint_failure_raises_proxy_token_mint_failed(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _local_settings(tmp_path)
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id, workspace_id="ws-test", prompt="test",
                state=RunState.queued.value, inference_mode="local",
                created_at=_now(), updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        token_client = _make_mock_token_client(
            raise_on_mint=ProxyTokenMintFailed("auth")
        )
        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings, session_factory=session_factory, bus=bus,
            token_client=token_client, static_md_text="# static",
        )

        with pytest.raises(ProxyTokenMintFailed):
            await spawner.spawn(_make_spawn_request(run_id, connector_name="my_conn"))

        # Verify no subprocess was started (no children registered)
        assert len(spawner._children) == 0

    @pytest.mark.asyncio
    async def test_cloud_mode_missing_api_key_raises_before_http(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """cloud mode + connector_name + missing SP_API_KEY → ProxyTokenMintFailed before HTTP."""
        settings = _cloud_settings(tmp_path, api_key=None)
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id, workspace_id="ws-test", prompt="test",
                state=RunState.queued.value, inference_mode="byo",
                created_at=_now(), updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        # Token client that would fail if called
        token_client = _make_mock_token_client(
            raise_on_mint=AssertionError("HTTP mint should not be called")
        )
        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings, session_factory=session_factory, bus=bus,
            token_client=token_client, static_md_text="# static",
        )

        req = SpawnRequest(
            run_id=run_id,
            workspace_id="ws-test",
            prompt="test",
            inference=InferenceBundle(
                mode="byo", oauth_token=None, api_key="sk-ant-testkey", base_url=None
            ),
            gateway_run_token=None,
            dbt_proxy_host_port=None,
            connector_name="my_conn",
            sandbox_internal_secret="aabbccdd" * 8,
        )

        with pytest.raises(ProxyTokenMintFailed) as exc_info:
            await spawner.spawn(req)

        assert "missing_api_key" in str(exc_info.value)
        # Ensure HTTP mint was never called
        token_client.mint.assert_not_called()


class TestSubprocessSpawnerStreaming:
    @pytest.mark.asyncio
    async def test_stdout_lines_arrive_as_events(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = _local_settings(tmp_path)
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id, workspace_id="ws-test", prompt="test",
                state=RunState.running.value, inference_mode="local",
                created_at=_now(), updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings, session_factory=session_factory, bus=bus,
            token_client=None, static_md_text="# static",
        )

        received_events: list = []
        async with bus.subscribe(run_id) as q:
            await spawner.spawn(_make_spawn_request(run_id, connector_name=None))

            # Wait for stream_end or timeout
            deadline = asyncio.get_event_loop().time() + 5
            while asyncio.get_event_loop().time() < deadline:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=0.5)
                    received_events.append(ev)
                    if ev.kind == "stream_end":
                        break
                except TimeoutError:
                    break

        await spawner.shutdown()

        stdout_events = [e for e in received_events if e.kind == "agent.stdout"]
        assert len(stdout_events) >= 1
        lines = [e.payload["line"] for e in stdout_events]
        assert any("fake_sandbox" in line for line in lines)


class TestSubprocessSpawnerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_terminates_children(
        self, tmp_path: Path, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_SANDBOX_SERVER_PATH": str(_FAKE_SANDBOX),
            "SP_RUN_WORKDIR_ROOT": str(tmp_path / "runs"),
            "SP_USE_SUBPROCESS_SPAWNER": "true",
            "SP_GATEWAY_URL": "http://gateway.test:3100",
            # Use a long lifetime so process doesn't exit naturally
            "FAKE_SANDBOX_LIFETIME_SECONDS": "60",
        })
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4()

        async with session_factory() as session:
            run = Run(
                id=run_id, workspace_id="ws-test", prompt="test",
                state=RunState.running.value, inference_mode="local",
                created_at=_now(), updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        bus = EventBus()
        spawner = SubprocessSpawner(
            settings=settings, session_factory=session_factory, bus=bus,
            token_client=None, static_md_text="# static",
        )

        await spawner.spawn(_make_spawn_request(run_id))
        assert run_id in spawner._children
        child = spawner._children[run_id]
        assert child.proc.returncode is None  # Still running

        await spawner.shutdown()

        # After shutdown, process should be dead
        assert child.proc.returncode is not None
