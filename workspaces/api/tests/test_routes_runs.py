"""Tests for run and approval routes."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workspaces_api.agent.spawner import SpawnRequest, StubSpawner
from workspaces_api.auth.dependency import current_user_id
from workspaces_api.config import Settings, get_settings
from workspaces_api.errors import ConnectorRequiresHostNet
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
        # Bypass auth for this test — it only tests inference mode, not auth
        app.dependency_overrides[current_user_id] = lambda: "user_test"

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
        del app.dependency_overrides[current_user_id]

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
        # Past-tense vocabulary since R6 (migration 0003)
        assert body["decision"] == "approved"

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
        # Past-tense vocabulary since R6 (migration 0003)
        assert body["decision"] == "rejected"
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

    async def test_local_mode_no_auth_header_passes(
        self, client: AsyncClient
    ) -> None:
        """Smoke: local mode requires no auth header for approval routes."""
        response = await client.post(
            f"/v1/runs/{uuid.uuid4()}/approve",
            json={"approval_id": str(uuid.uuid4())},
        )
        # 404 run_not_found (not 401) confirms auth bypass in local mode
        assert response.status_code == 404


class TestApprovalMarker:
    """Tests for the approval resume-marker writer wired into _handle_approval_decision."""

    def _ensure_resume_dir(self, workdir_root: Path, run_id: uuid.UUID) -> None:
        """Pre-create the resume dir (R8: write_approval_marker no longer creates it)."""
        resume_dir = workdir_root / str(run_id) / "home" / ".signalpilot" / "resume"
        resume_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

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

    async def test_decision_vocabulary_mapping(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
        app,
        settings_local: Settings,
    ) -> None:
        """C1: POST /approve → Approval.decision == 'approved', marker JSON decision == 'approved'."""
        # Override workdir root so marker is written to tmp_path
        custom_settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_RUN_WORKDIR_ROOT": str(tmp_path),
        })
        app.dependency_overrides[get_settings] = lambda: custom_settings

        run, approval = await self._create_run_awaiting_approval(session_factory)
        self._ensure_resume_dir(tmp_path, run.id)

        response = await client.post(
            f"/v1/runs/{run.id}/approve",
            json={"approval_id": str(approval.id)},
        )
        assert response.status_code == 200

        # DB column uses past tense
        async with session_factory() as session:
            updated = await session.get(Approval, approval.id)
            assert updated is not None
            assert updated.decision == "approved"

        # Marker file also uses past tense
        marker_path = (
            tmp_path / str(run.id) / "home" / ".signalpilot" / "resume"
            / f"{approval.id}.json"
        )
        assert marker_path.exists()
        data = json.loads(marker_path.read_text())
        assert data["decision"] == "approved"

        app.dependency_overrides[get_settings] = lambda: settings_local

    async def test_approve_writes_marker_file_with_decision_approved(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
        app,
        settings_local: Settings,
    ) -> None:
        custom_settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_RUN_WORKDIR_ROOT": str(tmp_path),
        })
        app.dependency_overrides[get_settings] = lambda: custom_settings

        run, approval = await self._create_run_awaiting_approval(session_factory)
        self._ensure_resume_dir(tmp_path, run.id)
        response = await client.post(
            f"/v1/runs/{run.id}/approve",
            json={"approval_id": str(approval.id)},
        )
        assert response.status_code == 200

        marker_path = (
            tmp_path / str(run.id) / "home" / ".signalpilot" / "resume"
            / f"{approval.id}.json"
        )
        assert marker_path.exists()
        data = json.loads(marker_path.read_text())
        assert data["decision"] == "approved"

        app.dependency_overrides[get_settings] = lambda: settings_local

    async def test_reject_writes_marker_file_with_decision_rejected(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
        app,
        settings_local: Settings,
    ) -> None:
        custom_settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_RUN_WORKDIR_ROOT": str(tmp_path),
        })
        app.dependency_overrides[get_settings] = lambda: custom_settings

        run, approval = await self._create_run_awaiting_approval(session_factory)
        self._ensure_resume_dir(tmp_path, run.id)
        response = await client.post(
            f"/v1/runs/{run.id}/reject",
            json={"approval_id": str(approval.id), "reason": "too risky"},
        )
        assert response.status_code == 200

        marker_path = (
            tmp_path / str(run.id) / "home" / ".signalpilot" / "resume"
            / f"{approval.id}.json"
        )
        assert marker_path.exists()
        data = json.loads(marker_path.read_text())
        assert data["decision"] == "rejected"
        assert data["comment"] == "too risky"

        app.dependency_overrides[get_settings] = lambda: settings_local

    async def test_marker_write_failure_does_not_block_response(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
        app,
        settings_local: Settings,
    ) -> None:
        """An OSError from the marker writer must not cause a non-200 response."""
        run, approval = await self._create_run_awaiting_approval(session_factory)

        with patch(
            "workspaces_api.routes.runs.write_approval_marker",
            side_effect=OSError("disk full"),
        ):
            response = await client.post(
                f"/v1/runs/{run.id}/approve",
                json={"approval_id": str(approval.id)},
            )
        assert response.status_code == 200

    async def test_marker_write_failure_emits_event_with_correlation_id(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
        app,
        settings_local: Settings,
    ) -> None:
        """OSError from writer → run.approval_marker_failed event in DB."""
        run, approval = await self._create_run_awaiting_approval(session_factory)

        with patch(
            "workspaces_api.routes.runs.write_approval_marker",
            side_effect=OSError("disk full"),
        ):
            response = await client.post(
                f"/v1/runs/{run.id}/approve",
                json={"approval_id": str(approval.id)},
            )
        assert response.status_code == 200

        # The failure event must be persisted to DB
        async with session_factory() as session:
            result = await session.execute(
                select(RunEvent).where(
                    RunEvent.run_id == run.id,
                    RunEvent.kind == "run.approval_marker_failed",
                )
            )
            events = list(result.scalars().all())
        assert len(events) == 1
        payload = events[0].payload
        assert "correlation_id" in payload
        assert payload["error"] == "OSError"
        assert payload["approval_id"] == str(approval.id)

    async def test_marker_write_uses_to_thread(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
        app,
        settings_local: Settings,
    ) -> None:
        """C7: write_approval_marker must be called from a non-main thread."""
        custom_settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_RUN_WORKDIR_ROOT": str(tmp_path),
        })
        app.dependency_overrides[get_settings] = lambda: custom_settings

        run, approval = await self._create_run_awaiting_approval(session_factory)

        thread_ids: list[int] = []

        original_writer = __import__(
            "workspaces_api.agent.resume_marker", fromlist=["write_approval_marker"]
        ).write_approval_marker

        def recording_writer(**kwargs):
            thread_ids.append(threading.get_ident())
            return original_writer(**kwargs)

        with patch(
            "workspaces_api.routes.runs.write_approval_marker",
            side_effect=recording_writer,
        ):
            response = await client.post(
                f"/v1/runs/{run.id}/approve",
                json={"approval_id": str(approval.id)},
            )
        assert response.status_code == 200
        assert len(thread_ids) == 1
        assert thread_ids[0] != threading.main_thread().ident

        app.dependency_overrides[get_settings] = lambda: settings_local


class TestConnectorRunscGuardAPI:
    """Addendum R8: connector spawn guard returns 409 at the API boundary."""

    async def test_runsc_connector_spawn_returns_409(
        self,
        client: AsyncClient,
        app,
        stub_spawner: StubSpawner,
    ) -> None:
        """POST /v1/runs with connector_name when runtime=runsc → 409 connector_requires_host_net."""

        class _RaisingSpawner:
            async def spawn(self, request: SpawnRequest) -> None:
                if request.connector_name:
                    raise ConnectorRequiresHostNet(
                        "Connector runs are not yet supported under the gvisor sandbox "
                        "(pending R9 host-net plumbing). "
                        f"connector={request.connector_name!r} runtime='runsc'. "
                        "Use runtime=none locally or omit connector_name."
                    )

            async def shutdown(self) -> None:
                pass

        from workspaces_api.routes.runs import _get_spawner

        app.dependency_overrides[_get_spawner] = lambda: _RaisingSpawner()

        response = await client.post(
            "/v1/runs",
            json={
                "workspace_id": "ws-001",
                "prompt": "analyse my sales data",
                "connector_name": "my_conn",
                "requested_inference": "local",
            },
        )

        del app.dependency_overrides[_get_spawner]

        assert response.status_code == 409
        body = response.json()
        assert body["error_code"] == "connector_requires_host_net"
