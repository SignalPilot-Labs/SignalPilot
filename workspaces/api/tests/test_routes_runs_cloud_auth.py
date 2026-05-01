"""Cloud-mode auth tests for run routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.fixtures.jwks import _factory
from workspaces_api.models import Run
from workspaces_api.states import RunState

_ISSUER = "https://fake-clerk.local"
_KID = "test-kid-0001"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _auth_header(sub: str) -> dict:
    token = _factory.mint_jwt(sub, kid=_KID, issuer=_ISSUER)
    return {"Authorization": f"Bearer {token}"}


class TestCloudAuthRuns:
    async def _create_run(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        user_id: str | None = "user_alice",
        workspace_id: str = "ws-001",
    ) -> Run:
        run = Run(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            prompt="test",
            state=RunState.running.value,
            inference_mode="byo",
            user_id=user_id,
            created_at=_now(),
            updated_at=_now(),
        )
        async with session_factory() as session:
            session.add(run)
            await session.commit()
        return run

    async def test_no_authorization_header_returns_401_with_error_code_auth_missing_token(
        self,
        client_cloud: AsyncClient,
    ) -> None:
        response = await client_cloud.get(f"/v1/runs/{uuid.uuid4()}")
        assert response.status_code == 401
        body = response.json()
        assert body["error_code"] == "auth_missing_token"

    async def test_invalid_jwt_returns_401_with_error_code_auth_invalid_token(
        self,
        client_cloud: AsyncClient,
    ) -> None:
        response = await client_cloud.get(
            f"/v1/runs/{uuid.uuid4()}",
            headers={"Authorization": "Bearer not.a.jwt"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error_code"] == "auth_invalid_token"

    async def test_submit_run_records_user_id_from_jwt_sub(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        response = await client_cloud.post(
            "/v1/runs",
            json={
                "workspace_id": "ws-001",
                "prompt": "test prompt",
                "requested_inference": "byo",
            },
            headers=_auth_header("user_alice"),
        )
        assert response.status_code == 201
        run_id = uuid.UUID(response.json()["id"])

        async with session_factory() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            assert run.user_id == "user_alice"

    async def test_get_run_returns_404_for_other_users_run(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        run = await self._create_run(session_factory, user_id="user_alice")

        # Bob requests Alice's run
        response = await client_cloud.get(
            f"/v1/runs/{run.id}", headers=_auth_header("user_bob")
        )
        assert response.status_code == 404

    async def test_get_run_returns_200_for_own_run(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        run = await self._create_run(session_factory, user_id="user_alice")
        response = await client_cloud.get(
            f"/v1/runs/{run.id}", headers=_auth_header("user_alice")
        )
        assert response.status_code == 200

    async def test_get_run_returns_404_for_legacy_null_user_id_row(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """C5: NULL user_id rows are invisible to cloud callers."""
        run = await self._create_run(session_factory, user_id=None)
        response = await client_cloud.get(
            f"/v1/runs/{run.id}", headers=_auth_header("user_alice")
        )
        assert response.status_code == 404

    async def test_list_runs_filters_by_user_id_and_excludes_null_rows(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """C5: List only returns caller's runs; NULL and other-user rows excluded."""
        await self._create_run(session_factory, user_id="user_alice", workspace_id="ws-list")
        await self._create_run(session_factory, user_id="user_bob", workspace_id="ws-list")
        await self._create_run(session_factory, user_id=None, workspace_id="ws-list")

        response = await client_cloud.get(
            "/v1/runs",
            params={"workspace_id": "ws-list"},
            headers=_auth_header("user_alice"),
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        # All returned runs belong to alice
        for item in body["items"]:
            assert item["id"] is not None  # no user_id on RunResponse per S6

    async def test_stream_events_returns_404_for_other_users_run_before_any_sse_frame(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """C6: SSE 404 fires before EventSourceResponse is returned."""
        run = await self._create_run(session_factory, user_id="user_alice")

        # Bob tries to stream Alice's events
        response = await client_cloud.get(
            f"/v1/runs/{run.id}/events",
            headers={
                **_auth_header("user_bob"),
                "Accept": "text/event-stream",
            },
        )
        # Must be 404 JSON, NOT 200 text/event-stream with deferred error
        assert response.status_code == 404
        assert "text/event-stream" not in response.headers.get("content-type", "")

    async def test_local_mode_unchanged(
        self,
        client: AsyncClient,
    ) -> None:
        """Smoke test: existing client (local mode) works without auth header."""
        response = await client.get(f"/v1/runs/{uuid.uuid4()}")
        # 404 run_not_found — not 401
        assert response.status_code == 404

    async def test_jwks_upstream_down_returns_503_not_401(
        self,
        app_cloud,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """C3: JWKS unavailable → 503 not 401."""
        import httpx
        from unittest.mock import AsyncMock
        from workspaces_api.auth.clerk import JwksClient

        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.get.side_effect = httpx.ConnectError("down")
        broken_client = JwksClient(
            jwks_url="https://clerk.example.com/.well-known/jwks.json",
            http_client=mock_http,
            ttl_seconds=0,
        )
        app_cloud.state.jwks_client = broken_client

        token = _factory.mint_jwt("user_abc", kid=_KID, issuer=_ISSUER)
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app_cloud),
            base_url="http://test",
        ) as c:
            response = await c.get(
                f"/v1/runs/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 503
        assert response.json()["error_code"] == "clerk_jwks_unavailable"
