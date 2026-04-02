"""HTTP client for the SignalPilot gateway REST API."""

from __future__ import annotations

from typing import Any

import httpx


class SignalPilotClient:
    """Thin async HTTP client that wraps the SignalPilot gateway API."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 60):
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    async def close(self):
        await self._client.aclose()

    # ── health ──────────────────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        r = await self._client.get("/health")
        r.raise_for_status()
        return r.json()

    # ── connections ──────────────────────────────────────────────────────────

    async def list_connections(self) -> list[dict[str, Any]]:
        r = await self._client.get("/api/connections")
        r.raise_for_status()
        return r.json()

    async def get_connection(self, name: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/connections/{name}")
        r.raise_for_status()
        return r.json()

    async def create_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.post("/api/connections", json=payload)
        r.raise_for_status()
        return r.json()

    async def delete_connection(self, name: str) -> dict[str, Any]:
        r = await self._client.delete(f"/api/connections/{name}")
        r.raise_for_status()
        return r.json()

    async def test_connection(self, name: str) -> dict[str, Any]:
        r = await self._client.post(f"/api/connections/{name}/test")
        r.raise_for_status()
        return r.json()

    async def get_schema(self, name: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/connections/{name}/schema")
        r.raise_for_status()
        return r.json()

    async def get_connection_health(self, name: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/connections/{name}/health")
        r.raise_for_status()
        return r.json()

    async def get_all_health(self) -> list[dict[str, Any]]:
        r = await self._client.get("/api/connections/health")
        r.raise_for_status()
        data = r.json()
        return data.get("connections", data) if isinstance(data, dict) else data

    # ── queries ──────────────────────────────────────────────────────────────

    async def query(self, connection_name: str, sql: str, row_limit: int = 1000) -> dict[str, Any]:
        r = await self._client.post("/api/query", json={
            "connection_name": connection_name,
            "sql": sql,
            "row_limit": row_limit,
        })
        r.raise_for_status()
        return r.json()

    # ── sandboxes ────────────────────────────────────────────────────────────

    async def list_sandboxes(self) -> list[dict[str, Any]]:
        r = await self._client.get("/api/sandboxes")
        r.raise_for_status()
        return r.json()

    async def create_sandbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.post("/api/sandboxes", json=payload)
        r.raise_for_status()
        return r.json()

    async def get_sandbox(self, sandbox_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/sandboxes/{sandbox_id}")
        r.raise_for_status()
        return r.json()

    async def delete_sandbox(self, sandbox_id: str) -> dict[str, Any]:
        r = await self._client.delete(f"/api/sandboxes/{sandbox_id}")
        r.raise_for_status()
        return r.json()

    async def execute_in_sandbox(self, sandbox_id: str, code: str, timeout: int = 30) -> dict[str, Any]:
        r = await self._client.post(f"/api/sandboxes/{sandbox_id}/execute", json={
            "code": code,
            "timeout": timeout,
        })
        r.raise_for_status()
        return r.json()

    # ── audit ────────────────────────────────────────────────────────────────

    async def audit_log(self, limit: int = 50, offset: int = 0, connection_name: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if connection_name:
            params["connection_name"] = connection_name
        r = await self._client.get("/api/audit", params=params)
        r.raise_for_status()
        data = r.json()
        # API returns {"entries": [...], "total": N}
        return data.get("entries", data) if isinstance(data, dict) else data

    # ── budget ───────────────────────────────────────────────────────────────

    async def get_budget(self, session_id: str = "default") -> dict[str, Any]:
        r = await self._client.get(f"/api/budget/{session_id}")
        r.raise_for_status()
        return r.json()

    async def create_budget(self, session_id: str, budget_usd: float) -> dict[str, Any]:
        r = await self._client.post("/api/budget", json={
            "session_id": session_id,
            "budget_usd": budget_usd,
        })
        r.raise_for_status()
        return r.json()

    # ── cache ────────────────────────────────────────────────────────────────

    async def cache_stats(self) -> dict[str, Any]:
        r = await self._client.get("/api/cache/stats")
        r.raise_for_status()
        return r.json()

    # ── settings ─────────────────────────────────────────────────────────────

    async def get_settings(self) -> dict[str, Any]:
        r = await self._client.get("/api/settings")
        r.raise_for_status()
        return r.json()

    async def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.put("/api/settings", json=payload)
        r.raise_for_status()
        return r.json()
