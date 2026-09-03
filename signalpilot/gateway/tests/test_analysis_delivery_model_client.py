"""Anthropic Messages transport error contracts."""

from __future__ import annotations

import os

import httpx
import pytest

from gateway.analysis_delivery.model_client import (
    AnthropicMessagesClient,
    AnthropicMessagesError,
    ClaudeAgentSDKResult,
    ClaudeAgentSDKStructuredClient,
)


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
async def test_claude_agent_sdk_client_uses_claude_code_contract_for_oauth() -> None:
    captured: dict = {}

    async def runner(prompt: str, options: dict) -> ClaudeAgentSDKResult:
        captured.update(prompt=prompt, options=options)
        assert os.path.isdir(options["cwd"])
        assert options["env"]["CLAUDE_CONFIG_DIR"] == options["cwd"]
        return ClaudeAgentSDKResult(
            structured_output={"summary": "Created it", "definition": {"name": "Revenue"}},
            is_error=False,
            usage={"input_tokens": 10},
        )

    client = ClaudeAgentSDKStructuredClient(
        oauth_token="oauth-token",
        timeout_seconds=1,
        query_runner=runner,
    )
    response = await client.create_message(
        {
            "model": "claude-test",
            "max_tokens": 100,
            "system": "Stay governed.",
            "messages": [{"role": "user", "content": "build a dashboard"}],
            "tools": [{"name": "submit", "input_schema": {"type": "object"}}],
            "tool_choice": {"type": "tool", "name": "submit"},
        }
    )

    options = captured["options"]
    assert captured["prompt"] == "build a dashboard"
    assert options["system_prompt"] == {
        "type": "preset",
        "preset": "claude_code",
        "append": "Stay governed.",
    }
    assert options["setting_sources"] == ["user"]
    assert options["tools"] == []
    assert options["permission_mode"] == "dontAsk"
    assert options["max_turns"] == 2
    assert options["output_format"] == {"type": "json_schema", "schema": {"type": "object"}}
    assert options["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token"
    assert options["env"]["ANTHROPIC_API_KEY"] == ""
    assert options["env"]["ANTHROPIC_AUTH_TOKEN"] == ""
    assert options["env"]["OAUTH_TOKEN"] == ""
    assert not os.path.exists(options["cwd"])
    assert response == {
        "content": [
            {
                "type": "tool_use",
                "name": "submit",
                "input": {"summary": "Created it", "definition": {"name": "Revenue"}},
            }
        ],
        "usage": {"input_tokens": 10},
    }


@pytest.mark.asyncio
async def test_claude_agent_sdk_client_preserves_safe_api_failure_status() -> None:
    async def runner(_prompt: str, _options: dict) -> ClaudeAgentSDKResult:
        return ClaudeAgentSDKResult(
            structured_output=None,
            is_error=True,
            api_error_status=429,
            error_type="rate_limit_error",
            provider_message="Rate limited",
            request_id="sdk-request-1",
        )

    client = ClaudeAgentSDKStructuredClient(
        oauth_token="oauth-token",
        timeout_seconds=1,
        query_runner=runner,
    )
    with pytest.raises(AnthropicMessagesError) as exc_info:
        await client.create_message(
            {
                "model": "claude-test",
                "system": "Stay governed.",
                "messages": [{"role": "user", "content": "build a dashboard"}],
                "tools": [{"name": "submit", "input_schema": {"type": "object"}}],
                "tool_choice": {"type": "tool", "name": "submit"},
            }
        )

    error = exc_info.value
    assert error.status_code == 429
    assert error.error_type == "rate_limit_error"
    assert error.request_id == "sdk-request-1"
    assert "oauth-token" not in str(error)


@pytest.mark.asyncio
async def test_claude_agent_sdk_client_preserves_result_when_structured_output_is_missing() -> None:
    async def runner(_prompt: str, _options: dict) -> ClaudeAgentSDKResult:
        return ClaudeAgentSDKResult(
            structured_output=None,
            is_error=False,
            provider_message="The generated response did not match the requested schema",
            request_id="sdk-request-2",
        )

    client = ClaudeAgentSDKStructuredClient(
        oauth_token="oauth-token",
        timeout_seconds=1,
        query_runner=runner,
    )
    with pytest.raises(AnthropicMessagesError) as exc_info:
        await client.create_message(
            {
                "model": "claude-test",
                "system": "Stay governed.",
                "messages": [{"role": "user", "content": "build a dashboard"}],
                "tools": [{"name": "submit", "input_schema": {"type": "object"}}],
                "tool_choice": {"type": "tool", "name": "submit"},
            }
        )

    error = exc_info.value
    assert error.error_type == "missing_structured_output"
    assert error.provider_message == "The generated response did not match the requested schema"
    assert error.request_id == "sdk-request-2"


@pytest.mark.asyncio
async def test_claude_agent_sdk_client_can_parse_bounded_json_without_native_output() -> None:
    captured: dict = {}

    async def runner(prompt: str, options: dict) -> ClaudeAgentSDKResult:
        captured.update(prompt=prompt, options=options)
        return ClaudeAgentSDKResult(
            structured_output=None,
            is_error=False,
            result_text='{"summary":"Created it","definition":{"name":"Revenue"}}',
        )

    client = ClaudeAgentSDKStructuredClient(
        oauth_token="oauth-token",
        timeout_seconds=1,
        use_native_structured_output=False,
        query_runner=runner,
    )
    response = await client.create_message(
        {
            "model": "claude-test",
            "system": "Stay governed.",
            "messages": [{"role": "user", "content": "build a dashboard"}],
            "tools": [{"name": "submit", "input_schema": {"type": "object"}}],
            "tool_choice": {"type": "tool", "name": "submit"},
        }
    )

    assert "output_format" not in captured["options"]
    assert "Return only the JSON object for submit" in captured["prompt"]
    assert response["content"][0]["input"] == {
        "summary": "Created it",
        "definition": {"name": "Revenue"},
    }
