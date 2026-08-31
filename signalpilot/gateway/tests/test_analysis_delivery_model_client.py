"""Anthropic Messages transport error contracts."""

from __future__ import annotations

import httpx
import pytest

from gateway.analysis_delivery.model_client import AnthropicMessagesClient, AnthropicMessagesError


@pytest.mark.asyncio
async def test_anthropic_messages_error_preserves_safe_provider_diagnostics() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "secret-key"
        return httpx.Response(
            400,
            headers={"request-id": "req-provider-1"},
            json={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "messages.0.content: Input is too long for the model context window",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model_client = AnthropicMessagesClient(api_key="secret-key", timeout_seconds=1, http_client=client)
        with pytest.raises(AnthropicMessagesError) as exc_info:
            await model_client.create_message(
                {
                    "model": "claude-test",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "hello"}],
                }
            )

    error = exc_info.value
    assert error.status_code == 400
    assert error.error_type == "invalid_request_error"
    assert error.provider_message == "messages.0.content: Input is too long for the model context window"
    assert error.request_id == "req-provider-1"
    assert error.request_body_chars > 0
    assert "secret-key" not in str(error)


@pytest.mark.asyncio
async def test_anthropic_messages_client_uses_oauth_bearer_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer oauth-token"
        assert request.headers["anthropic-beta"] == "oauth-2025-04-20"
        assert "x-api-key" not in request.headers
        return httpx.Response(200, json={"content": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model_client = AnthropicMessagesClient(
            oauth_token="oauth-token",
            timeout_seconds=1,
            http_client=client,
        )
        response = await model_client.create_message(
            {
                "model": "claude-test",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "hello"}],
            }
        )

    assert response == {"content": []}


def test_anthropic_messages_client_rejects_conflicting_credentials() -> None:
    with pytest.raises(ValueError, match="only one Anthropic credential"):
        AnthropicMessagesClient(
            api_key="api-key",
            oauth_token="oauth-token",
            timeout_seconds=1,
        )
