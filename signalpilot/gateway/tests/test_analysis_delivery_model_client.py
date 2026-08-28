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
