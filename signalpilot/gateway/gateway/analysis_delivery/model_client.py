"""Shared model-call transport for gateway analysis delivery agents."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class MessagesModelClient(Protocol):
    """Provider-neutral interface used by gateway model-backed components."""

    async def create_message(self, request_body: dict[str, Any]) -> dict[str, Any]: ...


class AnthropicMessagesClient:
    """Call Anthropic Messages with shared auth, timeout, and response handling."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = max(float(timeout_seconds), 0.1)
        self._http_client = http_client

    async def create_message(self, request_body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if self._http_client is not None:
            return await self._post(self._http_client, headers, request_body)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await self._post(client, headers, request_body)

    @staticmethod
    async def _post(
        client: httpx.AsyncClient,
        headers: dict[str, str],
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        response = await client.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Anthropic Messages API returned a non-object response")
        return data
