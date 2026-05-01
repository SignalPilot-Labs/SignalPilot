"""Cloud-mode auth tests for dashboard chart routes."""

from __future__ import annotations

from httpx import AsyncClient

from tests.fixtures.jwks import _factory

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
