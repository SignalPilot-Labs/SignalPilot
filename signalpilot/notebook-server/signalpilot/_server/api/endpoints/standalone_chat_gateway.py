"""Scoped gateway reads used by one standalone chat execution."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from signalpilot._server.auth.standalone_chat import ExecutionScope

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

    async def load_result(self, result_id: str) -> dict[str, Any]:
        return await self._get_json(
            f"/api/query/results/{result_id}",
            missing="Governed structured result not found",
            invalid="Invalid governed structured result",
        )

    async def load_report_catalog(self, cursor: str | None) -> dict[str, Any]:
        params = {"limit": "50"}
        if cursor:
            params["cursor"] = cursor
        return await self._get_json(
            f"/api/chat/runs/{self.run_id}/report-catalog",
            params=params,
            invalid="Invalid saved report catalog",
        )

    async def load_report_context(self, report_id: str) -> dict[str, Any]:
        return await self._get_json(
            f"/api/chat/runs/{self.run_id}/report-context/{report_id}",
            missing="Saved report not found",
            invalid="Invalid saved report context",
        )

    async def check_published_artifact(
        self,
        artifact_kind: str,
        artifact_filename: str,
    ) -> dict[str, Any]:
        return await self._get_json(
            f"/api/chat/runs/{self.run_id}/published-report-artifact",
            params={
                "artifact_kind": artifact_kind,
                "artifact_filename": artifact_filename,
            },
            invalid="Invalid published artifact state",
        )

    async def create_dashboard_preview(
        self,
        *,
        request: str,
        project_id: str,
        branch: str,
        commit_sha: str,
        timezone: str,
        authoring_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a private governed dashboard draft bound to this chat scope."""

        path = (
            f"/api/dashboard-authoring/sessions/{authoring_session_id}/messages"
            if authoring_session_id
            else "/api/dashboard-authoring/sessions"
        )
        payload = (
            {"prompt": request}
            if authoring_session_id
            else {
                "prompt": request,
                "project_id": project_id,
                "branch": branch,
                "commit_sha": commit_sha,
                "timezone": timezone,
            }
        )
        return await self._post_json(
            path,
            payload=payload,
            timeout=DASHBOARD_AUTHORING_TIMEOUT_SECONDS,
            invalid="Invalid dashboard authoring preview",
            failed="Dashboard preview could not be created",
        )

    def dashboard_creator(
        self,
        body: dict[str, Any],
        scope: ExecutionScope,
    ) -> Callable[[str, str, str | None], Awaitable[dict[str, Any]]]:
        """Bind `create_dashboard_preview` to one run's frozen scope.

        A follow-up on an existing draft must name the authoring session the
        run was warmed with; any other session id is rejected.
        """
        warm_context = body.get("warm_context") or {}
        active_session_id = (
            str(
                (warm_context.get("dashboard_authoring") or {}).get(
                    "authoring_session_id"
                )
                or ""
            )
            or None
        )

        async def create(
            request: str,
            timezone: str,
            authoring_session_id: str | None,
        ) -> dict[str, Any]:
            if (
                authoring_session_id
                and authoring_session_id != active_session_id
            ):
                raise ValueError(
                    "Dashboard authoring session is not active in this Data Chat"
                )
            return await self.create_dashboard_preview(
                request=request,
                project_id=scope.project_id,
                branch=scope.branch,
                commit_sha=scope.commit_sha,
                timezone=timezone,
                authoring_session_id=authoring_session_id,
            )

        return create
