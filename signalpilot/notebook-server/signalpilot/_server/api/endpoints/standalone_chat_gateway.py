"""Scoped gateway reads used by one standalone chat execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


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


@dataclass(kw_only=True)
class StandaloneGatewayClient:
    gateway_url: str
    token: str
    run_id: str

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
