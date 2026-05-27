# Copyright 2026 SignalPilot. All rights reserved.
"""Python SDK client for the SignalPilot Agent REST API.

Usage:
    import signalpilot as sp

    agent = sp.agent(model="claude-sonnet-4-20250514")

    # Synchronous — blocks until the agent finishes
    response = agent.run("Analyze the sales data")
    print(response.text)

    # Streaming — yields events as they arrive
    for event in agent.stream("Build a dashboard"):
        if event.type == "text_delta":
            print(event.content, end="", flush=True)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

import requests


@dataclass
class AgentEvent:
    """A streaming event from the agent."""

    type: str
    content: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] | None = None
    tool_call_id: str = ""
    is_error: bool = False
    cost_usd: float | None = None
    turn: int = 0
    idx: int = 0


@dataclass
class AgentResponse:
    """Complete response from a synchronous agent.run() call."""

    text: str = ""
    thinking: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float | None = None
    events: list[AgentEvent] = field(default_factory=list)


class AgentClient:
    """Client for the SignalPilot Agent REST API.

    Args:
        server_url: Base URL of the SignalPilot server (e.g. "http://localhost:2718")
        model: Claude model to use
        system_prompt: Optional custom system prompt
    """

    def __init__(
        self,
        server_url: str = "http://localhost:2718",
        model: str = "claude-sonnet-4-20250514",
        system_prompt: str | None = None,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._model = model
        self._system_prompt = system_prompt
        self._instance_id: str | None = None
        self._token: str | None = None
        self._message_history: list[dict[str, str]] = []

    @property
    def instance_id(self) -> str | None:
        return self._instance_id

    def _get_token(self) -> str:
        """Extract the server token from the home page HTML."""
        if self._token:
            return self._token
        resp = requests.get(self._server_url, timeout=10)
        resp.raise_for_status()
        match = re.search(r'data-token="([^"]+)"', resp.text)
        self._token = match.group(1) if match else ""
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Sp-Server-Token": self._get_token(),
        }

    def _ensure_instance(self) -> str:
        """Create an agent instance if one doesn't exist yet."""
        if self._instance_id:
            return self._instance_id

        resp = requests.post(
            f"{self._server_url}/api/agent/create",
            headers=self._headers(),
            json={
                "model": self._model,
                "systemPrompt": self._system_prompt,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._instance_id = data["instanceId"]
        return self._instance_id  # type: ignore[return-value]

    def stream(
        self,
        message: str,
        *,
        new_chat: bool = False,
        timeout: int = 300,
    ) -> Iterator[AgentEvent]:
        """Send a message and yield streaming events.

        Args:
            message: The message to send
            new_chat: If True, starts a fresh conversation
            timeout: Request timeout in seconds

        Yields:
            AgentEvent objects for each streaming event
        """
        instance_id = self._ensure_instance()
        self._message_history.append({"role": "user", "content": message})

        resp = requests.post(
            f"{self._server_url}/api/agent/message",
            headers=self._headers(),
            json={
                "instanceId": instance_id,
                "message": message,
                "newChat": new_chat,
                "messageHistory": self._message_history,
            },
            stream=True,
            timeout=timeout,
        )
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue

            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            event = AgentEvent(
                type=data.get("type", ""),
                content=data.get("content", ""),
                tool_name=data.get("tool_name", ""),
                tool_input=data.get("tool_input"),
                tool_call_id=data.get("tool_call_id", ""),
                is_error=data.get("is_error", False),
                cost_usd=data.get("cost_usd"),
                turn=data.get("turn", 0),
                idx=data.get("idx", 0),
            )

            yield event

            if event.type == "done":
                return

    def run(
        self,
        message: str,
        *,
        new_chat: bool = False,
        timeout: int = 300,
    ) -> AgentResponse:
        """Send a message and wait for the complete response.

        Args:
            message: The message to send
            new_chat: If True, starts a fresh conversation
            timeout: Request timeout in seconds

        Returns:
            AgentResponse with the full text, thinking, tool calls, and cost
        """
        response = AgentResponse()

        for event in self.stream(message, new_chat=new_chat, timeout=timeout):
            response.events.append(event)

            if event.type == "text_delta":
                response.text += event.content
            elif event.type == "text":
                # Final authoritative text — replaces accumulated deltas
                response.text = event.content
            elif event.type == "thinking_delta":
                response.thinking += event.content
            elif event.type == "thinking":
                # Final authoritative thinking — replaces accumulated deltas
                response.thinking = event.content
            elif event.type == "tool_use":
                response.tool_calls.append({
                    "name": event.tool_name,
                    "input": event.tool_input,
                    "id": event.tool_call_id,
                })
            elif event.type == "done":
                response.cost_usd = event.cost_usd

        if response.text:
            self._message_history.append({"role": "assistant", "content": response.text})

        return response

    def stop(self) -> bool:
        """Stop the running agent."""
        if not self._instance_id:
            return False

        resp = requests.post(
            f"{self._server_url}/api/agent/stop",
            headers=self._headers(),
            json={"instanceId": self._instance_id},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("success", False)

    def status(self) -> dict[str, Any]:
        """Get the current agent instance status."""
        if not self._instance_id:
            return {"error": "No instance created"}

        resp = requests.post(
            f"{self._server_url}/api/agent/status",
            headers=self._headers(),
            json={"instanceId": self._instance_id},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def list_instances(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """List all agent instances on the server."""
        resp = requests.post(
            f"{self._server_url}/api/agent/list",
            headers=self._headers(),
            json={"sessionId": session_id},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("instances", [])

    def get_events(self, after_index: int = -1) -> list[dict[str, Any]]:
        """Get buffered events for catch-up."""
        if not self._instance_id:
            return []

        resp = requests.post(
            f"{self._server_url}/api/agent/events",
            headers=self._headers(),
            json={"instanceId": self._instance_id, "afterIndex": after_index},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("events", [])

    def reset(self) -> None:
        """Reset the client — next message will create a fresh instance."""
        self._instance_id = None
        self._message_history = []


def agent(
    model: str = "claude-sonnet-4-20250514",
    server_url: str = "http://localhost:2718",
    system_prompt: str | None = None,
) -> AgentClient:
    """Create a new agent client.

    Args:
        model: Claude model to use
        server_url: Base URL of the SignalPilot server
        system_prompt: Optional custom system prompt

    Returns:
        AgentClient instance
    """
    return AgentClient(
        server_url=server_url,
        model=model,
        system_prompt=system_prompt,
    )
