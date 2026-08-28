"""Shared model-call transport for gateway analysis delivery agents."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
_ERROR_DETAIL_MAX_CHARS = 1_000


class AnthropicMessagesError(RuntimeError):
    """Structured upstream failure that never includes credentials or request content."""

    def __init__(
        self,
        *,
        status_code: int,
        error_type: str | None,
        provider_message: str | None,
        request_id: str | None,
        request_body_chars: int,
        retry_after: str | None,
    ) -> None:
        super().__init__(f"Anthropic Messages API request failed with status {status_code}")
        self.status_code = status_code
        self.error_type = error_type
        self.provider_message = provider_message
        self.request_id = request_id
        self.request_body_chars = request_body_chars
        self.retry_after = retry_after


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
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error_type, provider_message = _anthropic_error(response)
            raise AnthropicMessagesError(
                status_code=response.status_code,
                error_type=error_type,
                provider_message=provider_message,
                request_id=response.headers.get("request-id"),
                request_body_chars=_request_body_chars(request_body),
                retry_after=response.headers.get("retry-after"),
            ) from exc
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Anthropic Messages API returned a non-object response")
        return data


def _anthropic_error(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return _clean_detail(error.get("type")), _clean_detail(error.get("message"))
    return None, _clean_detail(response.text)


def _clean_detail(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    detail = " ".join(value.split()).strip()
    if not detail:
        return None
    return detail[:_ERROR_DETAIL_MAX_CHARS]


def _request_body_chars(request_body: dict[str, Any]) -> int:
    try:
        return len(json.dumps(request_body, ensure_ascii=True, separators=(",", ":")))
    except (TypeError, ValueError):
        return -1
