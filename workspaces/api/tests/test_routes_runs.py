"""Tests for run and approval routes."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workspaces_api.agent.spawner import StubSpawner
from workspaces_api.config import Settings, get_settings
from workspaces_api.events.bus import EventBus
from workspaces_api.models import Approval, Run, RunEvent
from workspaces_api.states import RunState


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class TestSubmitRun:
    async def test_submit_run_happy_path(
        self,
        client: AsyncClient,
        stub_spawner: StubSpawner,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        response = await client.post(
            "/v1/runs",
            json={
                "workspace_id": "ws-001",
                "prompt": "analyse my sales data",
                "requested_inference": "local",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["state"] == RunState.running.value
        assert body["inference_mode"] == "local"

        run_id = uuid.UUID(body["id"])

        async with session_factory() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            assert run.state == RunState.running.value

            from sqlalchemy import select
            result = await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id)
            )
            events = list(result.scalars().all())
            assert len(events) == 1
            assert events[0].kind == "run.started"

        assert len(stub_spawner.calls) == 1
        assert stub_spawner.calls[0].inference.mode == "local"

    async def test_submit_run_no_inference_returns_422(
        self,
        client: AsyncClient,
        app,
        settings_local: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # Override settings to have no token
        no_token_settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        })
        app.dependency_overrides[get_settings] = lambda: no_token_settings

        response = await client.post(
            "/v1/runs",
            json={
                "workspace_id": "ws-001",
                "prompt": "do something",
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "inference_not_configured"

        # Restore
        app.dependency_overrides[get_settings] = lambda: settings_local

    async def test_submit_run_metered_in_cloud_returns_501(
        self,
        client: AsyncClient,
        app,
        settings_cloud_byo: Settings,
        settings_local: Settings,
    ) -> None:
        app.dependency_overrides[get_settings] = lambda: settings_cloud_byo

        response = await client.post(
            "/v1/runs",
            json={
                "workspace_id": "ws-001",
                "prompt": "do something",
                "requested_inference": "metered",
            },
        )
        assert response.status_code == 501
        body = response.json()
        assert body["error_code"] == "metered_not_implemented"

        app.dependency_overrides[get_settings] = lambda: settings_local

    async def test_submit_run_prompt_too_long_returns_422(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/v1/runs",
            json={
                "workspace_id": "ws-001",
                "prompt": "x" * 16001,
            },
        )
        assert response.status_code == 422

    async def test_submit_run_no_row_created_when_inference_fails(
        self,
        client: AsyncClient,
        app,
        settings_local: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        no_token_settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        })
        app.dependency_overrides[get_settings] = lambda: no_token_settings

        await client.post(
            "/v1/runs",
            json={"workspace_id": "ws-001", "prompt": "do something"},
        )

        from sqlalchemy import select
        async with session_factory() as session:
            result = await session.execute(select(Run))
            runs = list(result.scalars().all())
        assert len(runs) == 0

        app.dependency_overrides[get_settings] = lambda: settings_local


class TestGetRun:
    async def test_get_run_200(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # Create a run directly
        run = Run(
            id=uuid.uuid4(),
            workspace_id="ws-001",
            prompt="test prompt",
            state=RunState.running.value,
            inference_mode="local",
            created_at=_now(),
            updated_at=_now(),
        )
        async with session_factory() as session:
            session.add(run)
            await session.commit()

        response = await client.get(f"/v1/runs/{run.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(run.id)
        assert body["state"] == RunState.running.value

    async def test_get_run_404(self, client: AsyncClient) -> None:
        response = await client.get(f"/v1/runs/{uuid.uuid4()}")
        assert response.status_code == 404


class TestStreamEvents:
    async def test_stream_events_404_for_unknown_run(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(
            f"/v1/runs/{uuid.uuid4()}/events",
            headers={"Accept": "text/event-stream"},
        )
        assert response.status_code == 404
        # Must NOT be text/event-stream (proves 404 fired before EventSourceResponse)
        assert "text/event-stream" not in response.headers.get("content-type", "")

    async def test_stream_events_replays_persisted_events(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        run = Run(
            id=uuid.uuid4(),
            workspace_id="ws-001",
            prompt="analyse",
            state=RunState.running.value,
            inference_mode="local",
            created_at=_now(),
            updated_at=_now(),
        )
        ev1 = RunEvent(run_id=run.id, kind="run.started", payload={})
        ev2 = RunEvent(run_id=run.id, kind="run.progress", payload={"pct": 50})
        # Sentinel stream_end event so the generator terminates
        ev_end = RunEvent(run_id=run.id, kind="stream_end", payload={})

        async with session_factory() as session:
            session.add(run)
            session.add(ev1)
            session.add(ev2)
            session.add(ev_end)
            await session.commit()

        response = await client.get(f"/v1/runs/{run.id}/events")
        assert response.status_code == 200
        content = response.text
        assert "run.started" in content
        assert "run.progress" in content
        assert "stream_end" in content

    async def test_stream_events_live_publish(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
    ) -> None:
        run = Run(
            id=uuid.uuid4(),
            workspace_id="ws-001",
            prompt="live test",
            state=RunState.running.value,
            inference_mode="local",
            created_at=_now(),
            updated_at=_now(),
        )
        async with session_factory() as session:
            session.add(run)
            await session.commit()

        from workspaces_api.schemas import RunEventOut

        stream_end_event = RunEventOut(
            id=999,
            run_id=run.id,
            kind="stream_end",
            payload={},
            created_at=_now(),
        )

        async def _publish_after_delay() -> None:
            await asyncio.sleep(0.05)
            await event_bus.publish(run.id, stream_end_event)

        task = asyncio.create_task(_publish_after_delay())
        response = await client.get(f"/v1/runs/{run.id}/events")
        await task

        assert response.status_code == 200
        assert "stream_end" in response.text


class TestApproveRun:
    async def _create_run_awaiting_approval(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> tuple[Run, Approval]:
        run = Run(
            id=uuid.uuid4(),
            workspace_id="ws-001",
            prompt="test",
            state=RunState.awaiting_approval.value,
            inference_mode="local",
            created_at=_now(),
            updated_at=_now(),
        )
        approval = Approval(
            id=uuid.uuid4(),
            run_id=run.id,
            tool_name="bash",
            tool_input={"cmd": "ls"},
            requested_at=_now(),
        )
        async with session_factory() as session:
            session.add(run)
            session.add(approval)
            await session.commit()
        return run, approval

    async def test_approve_run_happy_path(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        run, approval = await self._create_run_awaiting_approval(session_factory)

        response = await client.post(
            f"/v1/runs/{run.id}/approve",
            json={"approval_id": str(approval.id)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["decision"] == "approve"

        async with session_factory() as session:
            updated_run = await session.get(Run, run.id)
            assert updated_run is not None
            assert updated_run.state == RunState.running.value

            from sqlalchemy import select
            result = await session.execute(
                select(RunEvent).where(RunEvent.run_id == run.id)
            )
            events = [e.kind for e in result.scalars().all()]
            assert "approval.approve" in events

    async def test_reject_run_happy_path(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        run, approval = await self._create_run_awaiting_approval(session_factory)

        response = await client.post(
            f"/v1/runs/{run.id}/reject",
            json={"approval_id": str(approval.id), "reason": "too risky"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["decision"] == "reject"
        assert body["reason"] == "too risky"

        async with session_factory() as session:
            updated_run = await session.get(Run, run.id)
            assert updated_run is not None
            assert updated_run.state == RunState.cancelled.value

    async def test_approve_when_not_awaiting_returns_409(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        run = Run(
            id=uuid.uuid4(),
            workspace_id="ws-001",
            prompt="test",
            state=RunState.running.value,
            inference_mode="local",
            created_at=_now(),
            updated_at=_now(),
        )
        approval = Approval(
            id=uuid.uuid4(),
            run_id=run.id,
            tool_name="bash",
            tool_input={},
            requested_at=_now(),
        )
        async with session_factory() as session:
            session.add(run)
            session.add(approval)
            await session.commit()

        response = await client.post(
            f"/v1/runs/{run.id}/approve",
            json={"approval_id": str(approval.id)},
        )
        assert response.status_code == 409

    async def test_approve_unknown_run_returns_404(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            f"/v1/runs/{uuid.uuid4()}/approve",
            json={"approval_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404
