"""Shared model-call transport for gateway analysis delivery agents."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
    """Call Anthropic Messages with an API key, timeout, and response handling."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = max(float(timeout_seconds), 0.1)
        self._http_client = http_client

    async def create_message(self, request_body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "x-api-key": self.api_key or "",
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


@dataclass(frozen=True)
class ClaudeAgentSDKResult:
    """Provider-neutral subset of a completed Claude Agent SDK query."""

    structured_output: Any
    is_error: bool
    api_error_status: int | None = None
    error_type: str | None = None
    provider_message: str | None = None
    request_id: str | None = None
    usage: dict[str, Any] | None = None
    result_text: str | None = None


ClaudeAgentSDKRunner = Callable[[str, dict[str, Any]], Awaitable[ClaudeAgentSDKResult]]


class ClaudeAgentSDKStructuredClient:
    """Run OAuth-backed structured output through Claude Code's supported SDK."""

    def __init__(
        self,
        *,
        oauth_token: str,
        timeout_seconds: float,
        use_native_structured_output: bool = True,
        query_runner: ClaudeAgentSDKRunner | None = None,
    ) -> None:
        if not oauth_token:
            raise ValueError("Claude OAuth token is required")
        self.oauth_token = oauth_token
        self.timeout_seconds = max(float(timeout_seconds), 0.1)
        self.use_native_structured_output = use_native_structured_output
        self._query_runner = query_runner or _run_claude_agent_sdk_query

    async def create_message(self, request_body: dict[str, Any]) -> dict[str, Any]:
        prompt, system, tool_name, schema = _structured_request(request_body)
        agent_env = dict(os.environ)
        agent_env.update(
            {
                "ANTHROPIC_API_KEY": "",
                "ANTHROPIC_AUTH_TOKEN": "",
                "OAUTH_TOKEN": "",
                "CLAUDE_CODE_OAUTH_TOKEN": self.oauth_token,
            }
        )
        with tempfile.TemporaryDirectory(prefix="signalpilot-dashboard-authoring-") as runtime_dir:
            agent_env["CLAUDE_CONFIG_DIR"] = runtime_dir
            options: dict[str, Any] = {
                "model": request_body.get("model"),
                # Structured output requires a second SDK turn to emit the
                # validated JSON result after the initial model response.
                "max_turns": 2,
                "permission_mode": "dontAsk",
                "tools": [],
                "setting_sources": ["user"],
                "system_prompt": {
                    "type": "preset",
                    "preset": "claude_code",
                    "append": system,
                },
                "cwd": runtime_dir,
                "env": agent_env,
                "effort": _agent_effort(),
            }
            if self.use_native_structured_output:
                options["output_format"] = {"type": "json_schema", "schema": schema}
            else:
                prompt = _append_json_contract(prompt, tool_name=tool_name, schema=schema)
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    result = await self._query_runner(prompt, options)
            except TimeoutError as exc:
                raise _sdk_error(
                    request_body,
                    status_code=504,
                    error_type="claude_agent_sdk_timeout",
                    provider_message="Claude Agent SDK request timed out",
                ) from exc
            except AnthropicMessagesError:
                raise
            except Exception as exc:
                raise _sdk_error(
                    request_body,
                    status_code=503,
                    error_type="claude_agent_sdk_transport_error",
                    provider_message=type(exc).__name__,
                ) from exc

        if result.is_error:
            raise _sdk_error(
                request_body,
                status_code=result.api_error_status or 502,
                error_type=result.error_type or "claude_agent_sdk_error",
                provider_message=result.provider_message,
                request_id=result.request_id,
            )
        structured_output = result.structured_output
        if structured_output is None and not self.use_native_structured_output:
            structured_output = _parse_json_result(result.result_text)
        if structured_output is None:
            raise _sdk_error(
                request_body,
                status_code=502,
                error_type="missing_structured_output",
                provider_message=(
                    result.provider_message or "Claude Agent SDK returned no structured output"
                ),
                request_id=result.request_id,
            )
        return {
            "content": [
                {
                    "type": "tool_use",
                    "name": tool_name,
                    "input": structured_output,
                }
            ],
            "usage": result.usage or {},
        }


async def _run_claude_agent_sdk_query(prompt: str, options: dict[str, Any]) -> ClaudeAgentSDKResult:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    completed = None
    async for message in query(prompt=prompt, options=ClaudeAgentOptions(**options)):
        if isinstance(message, ResultMessage):
            completed = message
    if completed is None:
        raise RuntimeError("Claude Agent SDK query ended without a result")
    errors = getattr(completed, "errors", None)
    provider_message = completed.result
    if not provider_message and isinstance(errors, list):
        provider_message = "; ".join(str(error) for error in errors)
    return ClaudeAgentSDKResult(
        structured_output=completed.structured_output,
        is_error=completed.is_error,
        api_error_status=completed.api_error_status,
        error_type=completed.subtype,
        provider_message=_clean_detail(provider_message),
        request_id=completed.uuid or completed.session_id,
        usage=completed.usage if isinstance(completed.usage, dict) else None,
        result_text=completed.result,
    )


def _append_json_contract(prompt: str, *, tool_name: str, schema: dict[str, Any]) -> str:
    return (
        f"{prompt}\n\nReturn only the JSON object for {tool_name}. Do not use Markdown fences or add "
        "commentary. The object must match this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=True, separators=(',', ':'))}"
    )


def _parse_json_result(value: str | None) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _structured_request(request_body: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    system = request_body.get("system")
    messages = request_body.get("messages")
    tools = request_body.get("tools")
    tool_choice = request_body.get("tool_choice")
    if not isinstance(system, str) or not isinstance(messages, list) or not messages:
        raise ValueError("Claude Agent SDK structured request requires system and messages")
    if not isinstance(tool_choice, dict) or not isinstance(tool_choice.get("name"), str):
        raise ValueError("Claude Agent SDK structured request requires a named tool choice")
    tool_name = tool_choice["name"]
    tool = next(
        (item for item in tools or [] if isinstance(item, dict) and item.get("name") == tool_name),
        None,
    )
    if not isinstance(tool, dict) or not isinstance(tool.get("input_schema"), dict):
        raise ValueError("Claude Agent SDK structured request requires a tool input schema")
    prompt_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("Claude Agent SDK structured request supports text messages only")
        prompt_parts.append(message["content"])
    return "\n\n".join(prompt_parts), system, tool_name, tool["input_schema"]


def _agent_effort() -> str:
    effort = os.getenv("SP_AGENT_EFFORT", "medium").strip().lower()
    return effort if effort in {"low", "medium", "high", "xhigh", "max"} else "medium"


def _sdk_error(
    request_body: dict[str, Any],
    *,
    status_code: int,
    error_type: str,
    provider_message: str | None,
    request_id: str | None = None,
) -> AnthropicMessagesError:
    return AnthropicMessagesError(
        status_code=status_code,
        error_type=error_type,
        provider_message=_clean_detail(provider_message),
        request_id=request_id,
        request_body_chars=_request_body_chars(request_body),
        retry_after=None,
    )


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
