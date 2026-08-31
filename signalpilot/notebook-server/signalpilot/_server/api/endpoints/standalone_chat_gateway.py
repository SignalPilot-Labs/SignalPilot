"""Scoped gateway reads used by one standalone chat execution."""

from __future__ import annotations

from typing import Any

import httpx


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
