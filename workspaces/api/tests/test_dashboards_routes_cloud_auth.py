"""Cloud-mode auth tests for dashboard chart routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.fixtures.jwks import _factory
from workspaces_api.dashboards.models import Chart, ChartCache, ChartQuery
from workspaces_api.dashboards.cache import compute_cache_key

_ISSUER = "https://fake-clerk.local"
_KID = "test-kid-0001"

_BASE_CREATE = {
    "workspace_id": "ws-test",
    "title": "My Chart",
    "chart_type": "line",
    "echarts_option_json": {},
    "query": {
        "connector_name": "my_conn",
        "sql": "SELECT 1",
        "params": {},
        "refresh_interval_seconds": 3600,
    },
}


def _auth_header(sub: str = "user_alice") -> dict:
    token = _factory.mint_jwt(sub, kid=_KID, issuer=_ISSUER)
    return {"Authorization": f"Bearer {token}"}


async def _insert_chart(
    session_factory: async_sessionmaker[AsyncSession],
    workspace_id: str = "ws-test",
    created_by: str | None = "user_alice",
) -> tuple[Chart, ChartQuery]:
    """Insert a Chart + ChartQuery row with the given created_by value.

    This helper is used instead of chart_factory when we need to control
    created_by (chart_factory always leaves it NULL by default and does not
    accept a created_by parameter).
    """
    chart = Chart(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        title="Test Chart",
        chart_type="line",
        echarts_option={},
        created_by=created_by,
    )
    cq = ChartQuery(
        id=uuid.uuid4(),
        chart_id=chart.id,
        connector_name="my_conn",
        sql="SELECT 1",
        params={},
        refresh_interval_seconds=3600,
    )
    async with session_factory() as session:
        session.add(chart)
        await session.flush()
        session.add(cq)
        await session.flush()
        await session.commit()
    return chart, cq


class TestDashboardsCloudAuth:
    async def test_create_chart_requires_auth_in_cloud_mode_401(
        self,
        client_cloud: AsyncClient,
    ) -> None:
        response = await client_cloud.post("/v1/charts", json=_BASE_CREATE)
        assert response.status_code == 401
        assert response.json()["error_code"] == "auth_missing_token"

    async def test_create_chart_succeeds_with_valid_jwt(
        self,
        client_cloud: AsyncClient,
    ) -> None:
        response = await client_cloud.post(
            "/v1/charts",
            json=_BASE_CREATE,
            headers=_auth_header(),
        )
        assert response.status_code == 201

    async def test_local_mode_create_chart_unchanged(
        self,
        client: AsyncClient,
    ) -> None:
        """Smoke: local mode doesn't require auth header."""
        response = await client.post("/v1/charts", json=_BASE_CREATE)
        assert response.status_code == 201


class TestDashboardsCrossTenantOwnership:
    """Cross-tenant ACL tests for chart routes (Slice A, R7).

    Cloud mode enforces Chart.created_by == user_id. NULL created_by rows are
    local-mode sentinels invisible to cloud callers. 404 is returned, never 403.
    """

    async def test_get_chart_other_tenant_returns_404(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Alice creates chart; Bob's JWT GETs it → 404 chart_not_found."""
        chart, _ = await _insert_chart(session_factory, created_by="user_alice")
        response = await client_cloud.get(
            f"/v1/charts/{chart.id}",
            headers=_auth_header("user_bob"),
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == "chart_not_found"

    async def test_run_chart_other_tenant_returns_404(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Alice creates chart; Bob calls POST /run → 404 before cache lookup."""
        chart, _ = await _insert_chart(session_factory, created_by="user_alice")
        response = await client_cloud.post(
            f"/v1/charts/{chart.id}/run",
            json={"force": False, "params": None},
            headers=_auth_header("user_bob"),
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == "chart_not_found"

    async def test_run_chart_other_tenant_returns_404_even_when_cache_warm(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Ownership check fires BEFORE cache lookup — no timing oracle.

        Pre-seeds a cache row for alice's chart. Bob calls /run. Must still get
        404, confirming the ownership guard runs before any cache fetch path.
        """
        chart, cq = await _insert_chart(session_factory, created_by="user_alice")
        cache_key = compute_cache_key(cq.connector_name, cq.sql, cq.params)
        now = datetime.now(tz=timezone.utc)
        cache_row = ChartCache(
            cache_key=cache_key,
            query_id=cq.id,
            result_json={"columns": [], "rows": []},
            computed_at=now,
            expires_at=now.replace(year=now.year + 1),
        )
        async with session_factory() as session:
            session.add(cache_row)
            await session.commit()

        response = await client_cloud.post(
            f"/v1/charts/{chart.id}/run",
            json={"force": False, "params": None},
            headers=_auth_header("user_bob"),
        )
        assert response.status_code == 404
        assert response.json()["error_code"] == "chart_not_found"

    async def test_list_charts_excludes_other_tenant(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Alice creates chart in ws-shared; Bob lists ws-shared → empty items."""
        ws = "ws-shared-" + uuid.uuid4().hex[:8]
        await _insert_chart(session_factory, workspace_id=ws, created_by="user_alice")
        response = await client_cloud.get(
            "/v1/charts",
            params={"workspace": ws},
            headers=_auth_header("user_bob"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["next_cursor"] is None

    async def test_list_charts_excludes_null_created_by_legacy_rows(
        self,
        client_cloud: AsyncClient,
        chart_factory: Callable,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """NULL created_by rows (local-mode sentinel) are invisible to cloud callers.

        chart_factory creates rows with created_by=NULL (column omitted from
        constructor). This test confirms NULL != "user_bob" via SQL semantics,
        so the cloud list filter naturally excludes them.
        """
        ws = "ws-null-" + uuid.uuid4().hex[:8]
        # chart_factory leaves created_by=NULL by default
        await chart_factory(workspace_id=ws)
        response = await client_cloud.get(
            "/v1/charts",
            params={"workspace": ws},
            headers=_auth_header("user_bob"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["next_cursor"] is None

    async def test_create_chart_stamps_created_by_from_jwt_sub(
        self,
        client_cloud: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """POSTing a chart in cloud mode stamps created_by = JWT sub."""
        payload = {**_BASE_CREATE, "workspace_id": "ws-stamp"}
        response = await client_cloud.post(
            "/v1/charts",
            json=payload,
            headers=_auth_header("user_alice"),
        )
        assert response.status_code == 201
        chart_id = uuid.UUID(response.json()["id"])

        async with session_factory() as session:
            chart = await session.get(Chart, chart_id)
            assert chart is not None
            assert chart.created_by == "user_alice"

    async def test_local_mode_owner_match_not_required(
        self,
        client: AsyncClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Local-mode create then list returns the row with created_by IS NULL."""
        ws = "ws-local-" + uuid.uuid4().hex[:8]
        payload = {**_BASE_CREATE, "workspace_id": ws}
        response = await client.post("/v1/charts", json=payload)
        assert response.status_code == 201
        chart_id = uuid.UUID(response.json()["id"])

        async with session_factory() as session:
            chart = await session.get(Chart, chart_id)
            assert chart is not None
            assert chart.created_by is None

        list_response = await client.get("/v1/charts", params={"workspace": ws})
        assert list_response.status_code == 200
        body = list_response.json()
        assert len(body["items"]) == 1
