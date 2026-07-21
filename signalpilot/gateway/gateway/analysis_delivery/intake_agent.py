"""Tool-using intake agent for Slack/Notion routing decisions."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.analysis_delivery.intake_actions import (
    TERMINAL_ACTION_NAMES,
    IntakeTerminalAction,
    validate_terminal_action,
)
from gateway.analysis_delivery.intake_tools import INTAKE_READ_TOOL_NAMES, IntakeToolRunner
from gateway.string_utils import string_value as _string

LOGGER = logging.getLogger(__name__)

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_INTAKE_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_INTAKE_TIMEOUT_SECONDS = 12.0
DEFAULT_INTAKE_MAX_TOOL_CALLS = 6


class IntakeAgentError(RuntimeError):
    """Raised when intake cannot produce a valid terminal action."""


@dataclass(frozen=True)
class IntakeSession:
    source: str
    surface: str
    org_id: str
    user_id: str
    prompt: str
    source_thread_id: str
    source_url: str = ""
    previous_messages: list[str] = field(default_factory=list)
    continuation_state: dict[str, Any] = field(default_factory=dict)
    analysis_hint: dict[str, Any] = field(default_factory=dict)
    deliverable_context: dict[str, Any] = field(default_factory=dict)
    available_terminal_actions: tuple[str, ...] = TERMINAL_ACTION_NAMES
    active_stale_seconds: float = 30 * 60

    def to_model_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "surface": self.surface,
            "prompt": self.prompt,
            "sourceThreadId": self.source_thread_id,
            "sourceUrl": self.source_url,
            "previousMessages": self.previous_messages[-8:],
            "continuationState": self.continuation_state,
            "analysisHint": self.analysis_hint,
            "deliverableContext": self.deliverable_context,
            "availableTerminalActions": list(self.available_terminal_actions),
        }


@dataclass(frozen=True)
class IntakeToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    is_terminal: bool = False


@dataclass(frozen=True)
class IntakeAgentResult:
    action: IntakeTerminalAction
    tool_calls: list[IntakeToolCall] = field(default_factory=list)


class IntakeAgent:
    def __init__(
        self,
        *,
        provider: str = "anthropic",
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_tool_calls: int | None = None,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = (provider or "anthropic").strip().lower()
        self.model = (
            model
            or os.getenv("SIGNALPILOT_INTAKE_MODEL")
            or DEFAULT_INTAKE_MODEL
        ).strip()
        self.timeout_seconds = _float_env(
            "SIGNALPILOT_INTAKE_TIMEOUT_SECONDS",
            timeout_seconds,
            DEFAULT_INTAKE_TIMEOUT_SECONDS,
        )
        self.max_tool_calls = _int_env(
            "SIGNALPILOT_INTAKE_MAX_TOOL_CALLS",
            max_tool_calls,
            DEFAULT_INTAKE_MAX_TOOL_CALLS,
        )
        self.api_key = api_key or ""
        self._http_client = http_client

    async def run(self, session: IntakeSession, tool_runner: IntakeToolRunner) -> IntakeAgentResult:
        if self.provider != "anthropic" or not self.model or not self.api_key:
            raise IntakeAgentError("SignalPilot intake agent is not configured")

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": json.dumps(
                    session.to_model_payload(),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            }
        ]
        transcript: list[IntakeToolCall] = []
        read_tool_calls = 0
        for iteration in range(1, self.max_tool_calls + 1):
            response = await self._anthropic_request(messages, session)
            content = response.get("content") or []
            terminal_calls = _terminal_tool_uses(content)
            if terminal_calls:
                if len(terminal_calls) != 1:
                    raise IntakeAgentError("Intake agent called more than one terminal action")
                item = terminal_calls[0]
                name = _string(item.get("name"))
                args = _tool_args_dict(item)
                action = validate_terminal_action(
                    name,
                    args,
                    available_terminal_actions=session.available_terminal_actions,
                )
                transcript.append(IntakeToolCall(name=name, arguments=args, is_terminal=True))
                LOGGER.info(
                    "Intake agent selected terminal action source=%s surface=%s action=%s reads=%s iteration=%s",
                    session.source,
                    session.surface,
                    action.name,
                    read_tool_calls,
                    iteration,
                )
                return IntakeAgentResult(action=action, tool_calls=transcript)

            tool_results: list[dict[str, Any]] = []
            for item in _read_tool_uses(content):
                tool_use_id = _string(item.get("id"))
                name = _string(item.get("name"))
                args = _tool_args_dict(item)
                if not tool_use_id or args is None:
                    continue
                result = await _safe_read_tool_result(tool_runner, name, args)
                transcript.append(IntakeToolCall(name=name, arguments=args, result=result))
                read_tool_calls += 1
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result,
                    }
                )
            if not tool_results:
                raise IntakeAgentError("Intake agent did not call a terminal action")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": tool_results})
        raise TimeoutError(f"Intake agent exceeded tool call limit ({self.max_tool_calls})")

    async def _anthropic_request(self, messages: list[dict[str, Any]], session: IntakeSession) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "max_tokens": 900,
            "temperature": 0,
            "system": _intake_system_prompt(session),
            "tools": _intake_tools(session.available_terminal_actions),
            "messages": messages,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        if self._http_client is not None:
            response = await self._http_client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
            response.raise_for_status()
            return response.json()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(_ANTHROPIC_MESSAGES_URL, headers=headers, json=request_body)
            response.raise_for_status()
            return response.json()


async def run_intake_agent(
    session: IntakeSession,
    *,
    db: AsyncSession | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    api_key: str | None = None,
    raw_mcp_key: str | None = None,
    agent: IntakeAgent | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> IntakeAgentResult:
    runner = IntakeToolRunner(
        session=session,
        db=db,
        session_factory=session_factory,
        raw_mcp_key=raw_mcp_key,
    )
    intake_agent = agent or IntakeAgent(api_key=api_key, http_client=http_client)
    return await intake_agent.run(session, runner)


async def _safe_read_tool_result(tool_runner: IntakeToolRunner, name: str, args: dict[str, Any]) -> str:
    try:
        return await tool_runner.run(name, args)
    except Exception as exc:
        LOGGER.info("Intake read tool failed name=%s error=%s", name, exc, exc_info=True)
        return json.dumps({"error": str(exc)[:500]}, ensure_ascii=True)


def _terminal_tool_uses(content: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "tool_use"
        and _string(item.get("name")) in TERMINAL_ACTION_NAMES
    ]


def _read_tool_uses(content: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "tool_use"
        and _string(item.get("name")) in INTAKE_READ_TOOL_NAMES
    ]


def _tool_args_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    args = item.get("input")
    return args if isinstance(args, dict) else None


def _float_env(name: str, explicit: float | None, default: float) -> float:
    value = explicit if explicit is not None else os.getenv(name)
    try:
        return max(float(value), 0.1) if value is not None else default
    except (TypeError, ValueError):
        return default


def _int_env(name: str, explicit: int | None, default: int) -> int:
    value = explicit if explicit is not None else os.getenv(name)
    try:
        return max(int(value), 1) if value is not None else default
    except (TypeError, ValueError):
        return default


def _intake_system_prompt(session: IntakeSession) -> str:
    actions = ", ".join(session.available_terminal_actions)
    return (
        "You are SignalPilot's internal intake agent for Slack and Notion. "
        "You decide the next adapter action by using tools, not by keyword rules. "
        "Use read tools when product, org, connection, schema, project, knowledge, conversation, "
        "analysis status, trace, or deliverable context is needed. "
        "Answer directly only from adapter-provided facts or read-tool results. "
        "If live data work, SQL, charts, or metric computation is needed, choose a notebook action. "
        "For requests such as update the results, rerun with latest data, try again, or what changed, "
        "read analysis status and choose update_notebook_analysis when a safe trail exists. "
        "When the user explicitly asks to start fresh, start over, or rerun as a new analysis, "
        "choose start_notebook_analysis with fresh=true. Otherwise do not set fresh. "
        "For low-value acknowledgements or noise, choose react_or_ignore. "
        "For known Notion HTML deliverables, choose update_notion_deliverable when the user asks to edit or refresh it. "
        "You must end by calling exactly one terminal action tool and no more. "
        f"Available terminal actions on this surface: {actions}."
    )


def _intake_tools(available_terminal_actions: tuple[str, ...]) -> list[dict[str, Any]]:
    tools = list(_READ_TOOL_SCHEMAS)
    available = set(available_terminal_actions)
    tools.extend(schema for schema in _TERMINAL_TOOL_SCHEMAS if schema["name"] in available)
    return tools


_READ_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_current_conversation",
        "description": "Read the current Slack/Notion prompt, prior messages, continuation state, and surface hints.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_analysis_status",
        "description": "Read whether this source thread has an existing analysis and whether it is safe to update.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_analysis_trace_summary",
        "description": "Read a bounded sanitized summary of the prior analysis trace for this source thread.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_deliverable_context",
        "description": "Read saved Notion HTML deliverable metadata and refresh/edit availability for this comment.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_database_connections",
        "description": "List configured database connections. Does not run queries.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "connection_health",
        "description": "Check health stats for one or all configured database connections.",
        "input_schema": {
            "type": "object",
            "properties": {"connection_name": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "connector_capabilities",
        "description": "Read connector feature capabilities for one connection or all connector tiers.",
        "input_schema": {
            "type": "object",
            "properties": {"connection_name": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_workspace_projects",
        "description": "List notebook workspace projects and their active status.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "schema_overview",
        "description": "Read a compact overview of one database schema.",
        "input_schema": {
            "type": "object",
            "properties": {"connection_name": {"type": "string"}},
            "required": ["connection_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "schema_link",
        "description": "Read schema tables relevant to a natural-language question. Does not query data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_name": {"type": "string"},
                "question": {"type": "string"},
                "format": {"type": "string", "enum": ["ddl", "compact", "json"]},
                "max_tables": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["connection_name", "question"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_tables",
        "description": "List tables for a configured database connection. Does not query rows.",
        "input_schema": {
            "type": "object",
            "properties": {"connection_name": {"type": "string"}},
            "required": ["connection_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "describe_table",
        "description": "Read table columns and annotations.",
        "input_schema": {
            "type": "object",
            "properties": {"connection_name": {"type": "string"}, "table_name": {"type": "string"}},
            "required": ["connection_name", "table_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_knowledge",
        "description": "Load baseline org/project knowledge and optional task-specific docs.",
        "input_schema": {
            "type": "object",
            "properties": {"task_description": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "search_knowledge",
        "description": "Search SignalPilot knowledge docs by query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "scope": {"type": "string"},
                "scope_ref": {"type": "string"},
                "category": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_history",
        "description": "Read recent query history for a database connection. Does not run SQL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_name": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["connection_name"],
            "additionalProperties": False,
        },
    },
)

_TERMINAL_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "respond_to_user",
        "description": "Terminal action: post this direct answer to the user.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "minLength": 1}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "react_or_ignore",
        "description": "Terminal action: react to or silently ignore a low-value/noise message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["react", "ignore"]},
                "reaction": {"type": "string"},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "start_notebook_analysis",
        "description": "Terminal action: start a new notebook-backed analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "minLength": 1},
                "output_mode": {"type": "string", "enum": ["answer", "deliverable"]},
                "fresh": {
                    "type": "boolean",
                    "description": "True only when the user explicitly requests a new notebook identity.",
                },
            },
            "required": ["prompt", "output_mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_notebook_analysis",
        "description": "Terminal action: update an existing completed/stale notebook analysis for this source thread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "minLength": 1},
                "output_mode": {"type": "string", "enum": ["answer", "deliverable"]},
            },
            "required": ["prompt", "output_mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_notion_deliverable",
        "description": "Terminal action: edit or refresh an existing Notion HTML deliverable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["edit_existing", "refresh_data"]},
                "render_instruction": {"type": "string", "minLength": 1},
                "data_instruction": {"type": "string"},
            },
            "required": ["mode", "render_instruction"],
            "additionalProperties": False,
        },
    },
)
