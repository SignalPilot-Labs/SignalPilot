"""HTTP client for the SignalPilot self-improve monitor + agent APIs."""

from __future__ import annotations

from typing import Any

import httpx


class AgentClient:
    """Async HTTP client for the self-improve monitor (3401) and agent (8500) APIs."""

    def __init__(self, monitor_url: str, timeout: float = 30):
        self._client = httpx.AsyncClient(
            base_url=monitor_url.rstrip("/"),
            timeout=timeout,
        )

    async def close(self):
        await self._client.aclose()

    # ── Agent health & control ──────────────────────────────────────────────

    async def agent_health(self) -> dict[str, Any]:
        r = await self._client.get("/api/agent/health")
        r.raise_for_status()
        return r.json()

    async def start_run(
        self,
        prompt: str | None = None,
        max_budget_usd: float = 0,
        duration_minutes: float = 0,
        base_branch: str = "main",
    ) -> dict[str, Any]:
        r = await self._client.post("/api/agent/start", json={
            "prompt": prompt,
            "max_budget_usd": max_budget_usd,
            "duration_minutes": duration_minutes,
            "base_branch": base_branch,
        })
        r.raise_for_status()
        return r.json()

    async def stop_agent(self) -> dict[str, Any]:
        r = await self._client.post("/api/agent/stop")
        r.raise_for_status()
        return r.json()

    async def kill_agent(self) -> dict[str, Any]:
        r = await self._client.post("/api/agent/kill")
        r.raise_for_status()
        return r.json()

    async def resume_run(self, run_id: str, max_budget_usd: float = 0) -> dict[str, Any]:
        r = await self._client.post("/api/agent/resume", json={
            "run_id": run_id,
            "max_budget_usd": max_budget_usd,
        })
        r.raise_for_status()
        return r.json()

    async def list_branches(self) -> list[str]:
        r = await self._client.get("/api/agent/branches")
        r.raise_for_status()
        return r.json()

    # ── Runs ────────────────────────────────────────────────────────────────

    async def list_runs(self) -> list[dict[str, Any]]:
        r = await self._client.get("/api/runs")
        r.raise_for_status()
        return r.json()

    async def get_run(self, run_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/runs/{run_id}")
        r.raise_for_status()
        return r.json()

    async def get_tool_calls(self, run_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        r = await self._client.get(f"/api/runs/{run_id}/tools", params={"limit": limit, "offset": offset})
        r.raise_for_status()
        return r.json()

    async def get_run_audit(self, run_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        r = await self._client.get(f"/api/runs/{run_id}/audit", params={"limit": limit, "offset": offset})
        r.raise_for_status()
        return r.json()

    async def get_run_diff(self, run_id: str) -> dict[str, Any]:
        r = await self._client.get(f"/api/runs/{run_id}/diff")
        r.raise_for_status()
        return r.json()

    # ── Control signals ─────────────────────────────────────────────────────

    async def pause_run(self, run_id: str) -> dict[str, Any]:
        r = await self._client.post(f"/api/runs/{run_id}/pause")
        r.raise_for_status()
        return r.json()

    async def resume_run_signal(self, run_id: str) -> dict[str, Any]:
        r = await self._client.post(f"/api/runs/{run_id}/resume")
        r.raise_for_status()
        return r.json()

    async def inject_prompt(self, run_id: str, payload: str) -> dict[str, Any]:
        r = await self._client.post(f"/api/runs/{run_id}/inject", json={"payload": payload})
        r.raise_for_status()
        return r.json()

    async def stop_run(self, run_id: str, reason: str = "") -> dict[str, Any]:
        r = await self._client.post(f"/api/runs/{run_id}/stop", json={"payload": reason})
        r.raise_for_status()
        return r.json()

    async def unlock_run(self, run_id: str) -> dict[str, Any]:
        r = await self._client.post(f"/api/runs/{run_id}/unlock")
        r.raise_for_status()
        return r.json()
