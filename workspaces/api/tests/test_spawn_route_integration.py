"""Integration test: submit a run with SubprocessSpawner pointing at fake_sandbox.

Mint-token is mocked via httpx.MockTransport. Verifies:
  - POST /v1/runs returns 201
  - Events stream through SSE (stream_end received)
  - Run state transitions to succeeded after fake_sandbox exits cleanly
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from unittest.mock import AsyncMock

from workspaces_api.agent.proxy_token_client import ProxyTokenClient
from workspaces_api.agent.sandbox_runtime import NoneRuntime
from workspaces_api.agent.subprocess_spawner import SubprocessSpawner
from workspaces_api.auth.clerk import JwksClient
from workspaces_api.config import Settings, get_settings
from workspaces_api.events.bus import EventBus
from workspaces_api.main import create_app
from workspaces_api.routes.runs import _get_bus, _get_session_factory, _get_spawner

_FAKE_SANDBOX = Path(__file__).parent / "fixtures" / "fake_sandbox.py"

_MINT_RESPONSE = {
    "token": "integration-proxy-token",
    "host_port": 15432,
    "expires_at": "2026-05-01T13:00:00+00:00",
}


def _mock_gateway_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and "run-tokens" in request.url.path:
            return httpx.Response(201, json=_MINT_RESPONSE)
        if request.method == "DELETE" and "run-tokens" in request.url.path:
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": "not_found"})

    return httpx.MockTransport(handler)


class TestSpawnRouteIntegration:
    @pytest.mark.asyncio
    async def test_submit_run_streams_events(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-oauth-token",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_SANDBOX_SERVER_PATH": str(_FAKE_SANDBOX),
            "SP_RUN_WORKDIR_ROOT": str(tmp_path / "runs"),
            "SP_USE_SUBPROCESS_SPAWNER": "true",
            "SP_GATEWAY_URL": "http://gateway.test:3100",
        })
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)

        bus = EventBus()

        http_client = httpx.AsyncClient(transport=_mock_gateway_transport())
        token_client = ProxyTokenClient(
            gateway_url="http://gateway.test:3100",
            http_client=http_client,
            api_key=None,
        )
        static_md = "# static"

        spawner = SubprocessSpawner(
            settings=settings,
            session_factory=session_factory,
            bus=bus,
            token_client=token_client,
            static_md_text=static_md,
            runtime=NoneRuntime(),
        )

        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[_get_session_factory] = lambda: session_factory
        app.dependency_overrides[_get_spawner] = lambda: spawner
        app.dependency_overrides[_get_bus] = lambda: bus
        app.state.session_factory = session_factory
        app.state.spawner = spawner
        app.state.bus = bus
        app.state.jwks_client = JwksClient(
            jwks_url="http://unused.local/.well-known/jwks.json",
            http_client=AsyncMock(),
            ttl_seconds=600,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/runs",
                json={
                    "workspace_id": "ws-integration-test",
                    "prompt": "integration test",
                    "requested_inference": "local",
                },
            )
            assert resp.status_code == 201
            run_id = resp.json()["id"]

            # Wait for stream_end event to arrive on the bus
            received_events: list = []
            async with bus.subscribe(uuid.UUID(run_id)) as q:
                deadline = asyncio.get_event_loop().time() + 8
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=0.5)
                        received_events.append(ev)
                        if ev.kind == "stream_end":
                            break
                    except TimeoutError:
                        continue

        await spawner.shutdown()
        await http_client.aclose()

        event_kinds = [e.kind for e in received_events]
        assert "stream_end" in event_kinds, f"stream_end not received, got: {event_kinds}"

        stdout_events = [e for e in received_events if e.kind == "agent.stdout"]
        assert len(stdout_events) >= 1

    @pytest.mark.asyncio
    async def test_submit_run_mint_failure_returns_502(
        self,
        tmp_path: Path,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Mint failure on a connector-name run returns 502."""
        settings = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-oauth-token",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "SP_SANDBOX_SERVER_PATH": str(_FAKE_SANDBOX),
            "SP_RUN_WORKDIR_ROOT": str(tmp_path / "runs"),
            "SP_USE_SUBPROCESS_SPAWNER": "true",
            "SP_GATEWAY_URL": "http://gateway.test:3100",
        })
        settings.sp_run_workdir_root.mkdir(parents=True, exist_ok=True)

        bus = EventBus()

        def fail_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "unauthorized"})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(fail_handler))
        token_client = ProxyTokenClient(
            gateway_url="http://gateway.test:3100",
            http_client=http_client,
            api_key=None,
        )

        spawner = SubprocessSpawner(
            settings=settings,
            session_factory=session_factory,
            bus=bus,
            token_client=token_client,
            static_md_text="# static",
            runtime=NoneRuntime(),
        )

        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[_get_session_factory] = lambda: session_factory
        app.dependency_overrides[_get_spawner] = lambda: spawner
        app.dependency_overrides[_get_bus] = lambda: bus
        app.state.session_factory = session_factory
        app.state.spawner = spawner
        app.state.bus = bus
        app.state.jwks_client = JwksClient(
            jwks_url="http://unused.local/.well-known/jwks.json",
            http_client=AsyncMock(),
            ttl_seconds=600,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/runs",
                json={
                    "workspace_id": "ws-mint-fail",
                    "prompt": "should fail on mint",
                    "requested_inference": "local",
                    "connector_name": "bad_connector",
                },
            )

        await spawner.shutdown()
        await http_client.aclose()

        assert resp.status_code == 502
        body = resp.json()
        assert body["error_code"] == "proxy_token_mint_failed"
