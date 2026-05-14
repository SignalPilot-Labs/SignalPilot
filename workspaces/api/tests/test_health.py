"""Tests for GET /healthz."""

from __future__ import annotations

from httpx import AsyncClient


class TestHealth:
    async def test_healthz_returns_200_with_local_mode(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["deployment_mode"] == "local"
