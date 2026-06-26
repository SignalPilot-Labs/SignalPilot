"""Agent instance manager for concurrent agent execution.

Each agent instance has its own Claude conversation session, event buffer,
and lifecycle. Multiple agents can run simultaneously.

Three interfaces:
- Chat panel (frontend SSE via /api/ai/agent_chat)
- REST API (POST /api/agent/*)
- Python SDK (sp.agent())
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from signalpilot import _loggers
from signalpilot._server.ai.claude_agent import (
    AgentEvent,
    _get_system_prompt,
    run_notebook_agent,
    stop_agent,
)

LOGGER = _loggers.sp_logger()

MAX_BUFFER_EVENTS = 1000


@dataclass
class AgentInstance:
    """A single agent instance with its own conversation and event history."""

    id: str
    session_id: str
    status: str = "idle"  # idle, running, stopped, error
    created_at: float = 0.0
    message_count: int = 0
    model: str = "claude-sonnet-4-5-20250929"
    system_prompt: str = ""
    event_buffer: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None


class AgentManager:
    """Manages multiple concurrent agent instances."""

    def __init__(self) -> None:
        self._instances: dict[str, AgentInstance] = {}

    def create_instance(
        self,
        *,
        session_id: str | None = None,
        model: str = "claude-sonnet-4-5-20250929",
        system_prompt: str | None = None,
    ) -> AgentInstance:
        """Create a new agent instance."""
        import time

        instance_id = f"agent-{uuid.uuid4().hex[:12]}"
        sid = session_id or instance_id

        instance = AgentInstance(
            id=instance_id,
            session_id=sid,
            model=model,
            system_prompt=system_prompt or _get_system_prompt(),
            created_at=time.time(),
        )
        self._instances[instance_id] = instance
        LOGGER.info("Created agent instance %s", instance_id)
        return instance

    async def send_message(
        self,
        instance_id: str,
        message: str,
        *,
        new_chat: bool = False,
        message_history: list[dict[str, str]] | None = None,
        app: Any | None = None,
        context_file: str | None = None,
        cwd: str | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Send a message to an agent instance. Yields streaming events."""
        instance = self._instances.get(instance_id)
        if not instance:
            yield AgentEvent(
                type="error",
                content=f"Agent instance {instance_id} not found",
                is_error=True,
            )
            return

        instance.status = "running"
        instance.message_count += 1

        try:
            async for event in run_notebook_agent(
                message=message,
                session_id=instance.session_id,
                model=instance.model,
                new_chat=new_chat,
                message_history=message_history,
                system_prompt_override=instance.system_prompt,
                app=app,
                context_file=context_file,
                cwd=cwd,
            ):
                # Buffer the event for catch-up
                event_data = {
                    "type": event.type,
                    "content": event.content,
                    "tool_name": event.tool_name,
                    "tool_input": event.tool_input,
                    "tool_call_id": event.tool_call_id,
                    "is_error": event.is_error,
                    "cost_usd": event.cost_usd,
                    "turn": event.turn,
                }
                instance.event_buffer.append(event_data)
                if len(instance.event_buffer) > MAX_BUFFER_EVENTS:
                    instance.event_buffer = instance.event_buffer[-MAX_BUFFER_EVENTS:]

                yield event

            instance.status = "idle"
        except Exception as e:
            instance.status = "error"
            instance.last_error = str(e)
            yield AgentEvent(
                type="error",
                content=str(e),
                is_error=True,
            )

    def stop_instance(self, instance_id: str) -> bool:
        """Stop a running agent instance."""
        instance = self._instances.get(instance_id)
        if not instance:
            return False

        result = stop_agent(instance.session_id)
        if result:
            instance.status = "stopped"
        return result

    def get_instance(self, instance_id: str) -> AgentInstance | None:
        """Get an agent instance by ID."""
        return self._instances.get(instance_id)

    def list_instances(self, session_id: str | None = None) -> list[AgentInstance]:
        """List all agent instances, optionally filtered by session."""
        instances = list(self._instances.values())
        if session_id:
            instances = [i for i in instances if i.session_id == session_id]
        return sorted(instances, key=lambda i: i.created_at, reverse=True)

    def get_events(
        self, instance_id: str, after_index: int = -1
    ) -> list[dict[str, Any]]:
        """Get buffered events for catch-up after tab refocus."""
        instance = self._instances.get(instance_id)
        if not instance:
            return []
        return instance.event_buffer[after_index + 1 :]

    def clear_events(self, instance_id: str) -> None:
        """Clear the event buffer for an instance."""
        instance = self._instances.get(instance_id)
        if instance:
            instance.event_buffer.clear()

    def delete_instance(self, instance_id: str) -> bool:
        """Delete an agent instance."""
        if instance_id in self._instances:
            self.stop_instance(instance_id)
            del self._instances[instance_id]
            return True
        return False


# Global singleton
_manager: AgentManager | None = None


def get_agent_manager() -> AgentManager:
    """Get or create the global agent manager."""
    global _manager
    if _manager is None:
        _manager = AgentManager()
    return _manager
