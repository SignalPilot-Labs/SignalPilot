"""H1 verification tests: SpawnFailed / ProxyTokenMintFailed in submit_run.

Verifies:
  - Response body is exactly {error_code, correlation_id} (no message)
  - A RunEvent(kind="run.failed", payload={...}) row exists for the run
  - Bus received the run.failed event
  - Run state is "failed" with finished_at set
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workspaces_api.agent.spawner import SpawnRequest
from workspaces_api.errors import ProxyTokenMintFailed, SpawnFailed
from workspaces_api.events.bus import EventBus
from workspaces_api.models import Run, RunEvent
from workspaces_api.states import RunState

_CORRELATION_ID = "aabbccdd11223344"


class FailingSpawnerSpawnFailed:
    """Spawner that raises SpawnFailed on every spawn call."""

    calls: list[SpawnRequest]

    def __init__(self) -> None:
        self.calls = []

    async def spawn(self, request: SpawnRequest) -> None:
        self.calls.append(request)
        raise SpawnFailed("subprocess exec failed: FileNotFoundError", correlation_id=_CORRELATION_ID)

    async def shutdown(self) -> None:
        pass


class FailingSpawnerMintFailed:
    """Spawner that raises ProxyTokenMintFailed on every spawn call."""

    calls: list[SpawnRequest]

    def __init__(self) -> None:
        self.calls = []

    async def spawn(self, request: SpawnRequest) -> None:
        self.calls.append(request)
        raise ProxyTokenMintFailed("auth", correlation_id=_CORRELATION_ID)

    async def shutdown(self) -> None:
        pass


class TestRunsFailureEvent:
    @pytest.mark.asyncio
    async def test_spawn_failed_response_has_error_code_and_correlation_id_only(
        self,
        client: AsyncClient,
        app: object,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
    ) -> None:
        from workspaces_api.routes.runs import _get_bus, _get_spawner

        spawner = FailingSpawnerSpawnFailed()
        app.dependency_overrides[_get_spawner] = lambda: spawner  # type: ignore[attr-defined]
        app.dependency_overrides[_get_bus] = lambda: event_bus  # type: ignore[attr-defined]
        app.state.bus = event_bus  # type: ignore[attr-defined]

        resp = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws-fail", "prompt": "run me", "requested_inference": "local"},
        )

        assert resp.status_code == 500
        body = resp.json()
        assert set(body.keys()) == {"error_code", "correlation_id"}
        assert body["error_code"] == "spawn_failed"
        assert body["correlation_id"] == _CORRELATION_ID
        assert "message" not in body

    @pytest.mark.asyncio
    async def test_spawn_failed_emits_run_failed_event_in_db(
        self,
        client: AsyncClient,
        app: object,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
    ) -> None:
        from workspaces_api.routes.runs import _get_bus, _get_spawner

        spawner = FailingSpawnerSpawnFailed()
        app.dependency_overrides[_get_spawner] = lambda: spawner  # type: ignore[attr-defined]
        app.dependency_overrides[_get_bus] = lambda: event_bus  # type: ignore[attr-defined]
        app.state.bus = event_bus  # type: ignore[attr-defined]

        resp = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws-fail", "prompt": "run me", "requested_inference": "local"},
        )
        assert resp.status_code == 500

        # Find the run that was created
        async with session_factory() as session:
            result = await session.execute(
                select(Run).order_by(Run.created_at.desc()).limit(1)
            )
            run = result.scalar_one_or_none()
            assert run is not None
            assert run.state == RunState.failed.value
            assert run.finished_at is not None

            ev_result = await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run.id)
                .order_by(RunEvent.id)
            )
            events = list(ev_result.scalars().all())

        kinds = [e.kind for e in events]
        assert "run.failed" in kinds, f"run.failed not in {kinds}"
        failed_ev = next(e for e in events if e.kind == "run.failed")
        assert failed_ev.payload["error_code"] == "spawn_failed"
        assert failed_ev.payload["correlation_id"] == _CORRELATION_ID

    @pytest.mark.asyncio
    async def test_proxy_token_mint_failed_response_shape_and_db_event(
        self,
        client: AsyncClient,
        app: object,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
    ) -> None:
        from workspaces_api.routes.runs import _get_bus, _get_spawner

        spawner = FailingSpawnerMintFailed()
        app.dependency_overrides[_get_spawner] = lambda: spawner  # type: ignore[attr-defined]
        app.dependency_overrides[_get_bus] = lambda: event_bus  # type: ignore[attr-defined]
        app.state.bus = event_bus  # type: ignore[attr-defined]

        resp = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws-mint-fail", "prompt": "try it", "requested_inference": "local"},
        )
        assert resp.status_code == 502
        body = resp.json()
        assert set(body.keys()) == {"error_code", "correlation_id"}
        assert body["error_code"] == "proxy_token_mint_failed"
        assert body["correlation_id"] == _CORRELATION_ID
        assert "message" not in body

        async with session_factory() as session:
            result = await session.execute(
                select(Run).order_by(Run.created_at.desc()).limit(1)
            )
            run = result.scalar_one_or_none()
            assert run is not None
            assert run.state == RunState.failed.value

            ev_result = await session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run.id)
            )
            events = list(ev_result.scalars().all())

        kinds = [e.kind for e in events]
        assert "run.failed" in kinds, f"run.failed not in {kinds}"
