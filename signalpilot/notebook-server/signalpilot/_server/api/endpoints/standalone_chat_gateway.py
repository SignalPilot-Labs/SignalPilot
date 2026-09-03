"""Scoped gateway reads used by one standalone chat execution."""

from __future__ import annotations

import os
from typing import Any

import httpx

DASHBOARD_AUTHORING_TIMEOUT_SECONDS = 1_200.0


def gateway_api_base_url() -> str:
    """The gateway REST base for this sandbox, without any `/mcp` suffix."""
    return (
        str(
            os.getenv("SP_GATEWAY_INTERNAL_URL")
            or os.getenv("SP_GATEWAY_URL")
            or "http://gateway:3300"
        )
        .rstrip("/")
        .removesuffix("/mcp")
    )


class StandaloneGatewayClient:
    def __init__(
        self,
        *,
        gateway_url: str,
        token: str,
        run_id: str,
    ) -> None:
        self.gateway_url = gateway_url
        self.token = token
        self.run_id = run_id

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        missing: str | None = None,
        invalid: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.gateway_url}{path}",
                params=params,
                headers=self._headers,
            )
        if getattr(response, "status_code", None) == 404 and missing:
            raise ValueError(missing)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError(invalid)
        return value

    async def _post_json(
        self,
        path: str,
        *,
        payload: dict[str, Any],
        timeout: float = 30.0,
        invalid: str,
        failed: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.gateway_url}{path}",
                json=payload,
                headers=self._headers,
            )
        if getattr(response, "is_error", False):
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("detail") or "").strip()
            except (TypeError, ValueError):
                detail = ""
            raise ValueError(f"{failed}: {detail}" if detail else failed)
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError(invalid)
        return value

    async def dashboard_authoring_tool(
        self,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one model-free authoring mutation through the run token."""

        payload = dict(arguments)
        session_id = str(payload.pop("authoring_session_id", "") or "")
        if tool == "begin_dashboard_authoring":
            path = "/api/dashboard-authoring/begin"
            if session_id:
                payload["authoring_session_id"] = session_id
        elif tool == "set_dashboard_plan":
            path = f"/api/dashboard-authoring/sessions/{session_id}/plan"
        elif tool == "upsert_dashboard_chart":
            chart_id = str(payload.pop("chart_id", "") or "")
            path = (
                f"/api/dashboard-authoring/sessions/{session_id}/charts/"
                f"{chart_id}"
            )
        elif tool == "apply_dashboard_operations":
            path = f"/api/dashboard-authoring/sessions/{session_id}/operations"
        elif tool == "create_dashboard_preview":
            path = f"/api/dashboard-authoring/sessions/{session_id}/finalize"
        else:
            raise ValueError("Unknown dashboard authoring tool")
        if tool != "begin_dashboard_authoring" and not session_id:
            raise ValueError("Dashboard authoring session is required")
        return await self._post_json(
            path,
            payload=payload,
            timeout=DASHBOARD_AUTHORING_TIMEOUT_SECONDS,
            invalid="Invalid dashboard authoring result",
            failed="Dashboard authoring tool failed",
        )
