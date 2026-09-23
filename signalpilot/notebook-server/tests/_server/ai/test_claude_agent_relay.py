"""Relay loop: steering handshake and the run completion guard."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    ToolUseBlock,
    UserMessage,
)

from signalpilot._server.ai import claude_agent, claude_agent_events
from signalpilot._server.ai.claude_agent_events import (
    MAX_PLAN_CONTINUATIONS,
    PLAN_CONTINUATION_PROMPT,
    _relay_sdk_messages,
    _SdkStreamState,
    open_todo_count,
)
from signalpilot._server.ai.claude_agent_state import AgentEvent, _ActiveAgent

if TYPE_CHECKING:
    import queue


def _result(*, is_error: bool = False, num_turns: int = 1) -> ResultMessage:
    return ResultMessage(
        subtype="error" if is_error else "success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=num_turns,
        session_id="sdk-session",
        result="failed" if is_error else None,
    )


def _todo(*statuses: str) -> AssistantMessage:
    return AssistantMessage(
        content=[
            ToolUseBlock(
                id="todo-1",
                name="TodoWrite",
                input={
                    "todos": [
                        {"content": f"step {index}", "status": status}
                        for index, status in enumerate(statuses)
                    ]
                },
            )
        ],
        model="test-model",
    )


class FakeClient:
    """Yields queued SDK messages; ``query`` appends the next result."""

    def __init__(self, messages: list[Any]) -> None:
        self.messages: asyncio.Queue[Any] = asyncio.Queue()
        for message in messages:
            self.messages.put_nowait(message)
        self.queries: list[str] = []
        self.sent: list[dict[str, Any]] = []
        self.pending_at_query: list[int] = []
        self.agent: _ActiveAgent | None = None

    async def receive_messages(self):
        while True:
            message = await self.messages.get()
            if message is None:
                return
            yield message

    async def query(self, message: Any) -> None:
        if not isinstance(message, str):
            # A stream-json prompt (steering): record its text and uuid.
            async for item in message:
                self.sent.append(item)
                message = item["message"]["content"]
        self.queries.append(message)
        if self.agent is not None:
            self.pending_at_query.append(self.agent.pending_steering_turns)
        await self.messages.put(_result())


def _drain(event_queue: queue.Queue[Any]) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    while not event_queue.empty():
        events.append(event_queue.get_nowait())
    return events


@pytest.fixture(autouse=True)
def _fast_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_agent_events, "STEERING_GRACE_SECONDS", 0.05)


def test_open_todo_count_ignores_completed_items() -> None:
    assert open_todo_count(None) == 0
    assert open_todo_count({"todos": "nope"}) == 0
    assert (
        open_todo_count(
            {
                "todos": [
                    {"status": "completed"},
                    {"status": "in_progress"},
                    {"status": "pending"},
                ]
            }
        )
        == 2
    )


@pytest.mark.asyncio
async def test_steering_accepted_during_completion_window_keeps_run_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _ActiveAgent()
    client = FakeClient([_result()])
    client.agent = agent
    agent.client = client
    agent.loop = asyncio.get_running_loop()
    agent.task = asyncio.create_task(asyncio.Event().wait())
    monkeypatch.setitem(
        claude_agent._active_agents, "standalone-run-steer", agent
    )
    state = _SdkStreamState()
    relay = asyncio.create_task(
        _relay_sdk_messages(client, agent, agent.event_queue, state)
    )
    # The first ResultMessage is consumed at once; the steering message
    # lands inside the grace window that follows it.
    await asyncio.sleep(0.01)
    accepted = await claude_agent.steer_agent(
        "standalone-run-steer", "also check refunds", "steer-1"
    )
    assert accepted is True
    # The counter was incremented BEFORE the query reached the client.
    assert client.pending_at_query == [1]
    await asyncio.wait_for(relay, timeout=5)

    done_events = [e for e in _drain(agent.event_queue) if e.type == "done"]
    assert len(done_events) == 2
    assert client.queries == ["also check refunds"]
    # Sent with its steering id as the uuid, so the CLI's echo names it.
    assert client.sent[0]["uuid"] == "steer-1"
    assert agent.pending_steering_turns == 0
    assert agent.closing is True
    # Once the relay has closed the client, late steering is refused
    # instead of being queued on an exiting client.
    assert (
        await claude_agent.steer_agent(
            "standalone-run-steer", "too late", "steer-2"
        )
        is False
    )
    assert client.queries == ["also check refunds"]
    agent.task.cancel()


@pytest.mark.asyncio
async def test_open_todos_trigger_at_most_two_continuations() -> None:
    agent = _ActiveAgent()
    client = FakeClient([_todo("completed", "pending", "in_progress"), _result()])
    state = _SdkStreamState()

    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, state),
        timeout=5,
    )

    assert client.queries == [PLAN_CONTINUATION_PROMPT] * MAX_PLAN_CONTINUATIONS
    assert state.plan_continuations == MAX_PLAN_CONTINUATIONS
    events = _drain(agent.event_queue)
    # Continuation turns emit no terminal event; only the accepted result
    # after the budget is spent does.
    assert [e.type for e in events if e.type in {"done", "error"}] == ["done"]


@pytest.mark.asyncio
async def test_completed_plan_or_error_result_does_not_continue() -> None:
    agent = _ActiveAgent()
    client = FakeClient([_todo("completed", "completed"), _result()])
    state = _SdkStreamState()
    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, state),
        timeout=5,
    )
    assert client.queries == []
    assert [e.type for e in _drain(agent.event_queue)] == ["tool_use", "done"]

    agent = _ActiveAgent()
    client = FakeClient([_todo("pending"), _result(is_error=True)])
    state = _SdkStreamState()
    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, state),
        timeout=5,
    )
    assert client.queries == []
    assert [e.type for e in _drain(agent.event_queue)] == ["tool_use", "error"]


@pytest.mark.asyncio
async def test_zero_turn_result_before_the_user_message_is_skipped() -> None:
    # A resume after an unfinished background task: the CLI answers its own
    # injected turn first (zero API turns), then the queued user message.
    agent = _ActiveAgent()
    answer = AssistantMessage(content=[ToolUseBlock(id="q", name="query", input={})], model="m")
    client = FakeClient([_result(num_turns=0), answer, _result(num_turns=3)])
    state = _SdkStreamState()
    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, state),
        timeout=5,
    )
    assert state.skipped_empty_results == 1
    assert [e.type for e in _drain(agent.event_queue)] == ["tool_use", "done"]

    # A result the SDK attributes to a task notification is skipped too.
    notified = _result(num_turns=2)
    notified.origin = {"kind": "task-notification"}
    agent = _ActiveAgent()
    client = FakeClient([notified, answer, _result(num_turns=3)])
    state = _SdkStreamState()
    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, state),
        timeout=5,
    )
    assert state.skipped_empty_results == 1
    assert [e.type for e in _drain(agent.event_queue)] == ["tool_use", "done"]


@pytest.mark.asyncio
async def test_zero_turn_results_are_skipped_at_most_twice() -> None:
    agent = _ActiveAgent()
    client = FakeClient([_result(num_turns=0)] * 3)
    state = _SdkStreamState()
    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, state),
        timeout=5,
    )
    assert state.skipped_empty_results == 2
    assert [e.type for e in _drain(agent.event_queue)] == ["done"]

    # An error result is never skipped.
    agent = _ActiveAgent()
    client = FakeClient([_result(is_error=True, num_turns=0)])
    state = _SdkStreamState()
    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, state),
        timeout=5,
    )
    assert [e.type for e in _drain(agent.event_queue)] == ["error"]


def test_error_text_never_uses_the_repr() -> None:
    import httpx

    assert (
        claude_agent._error_text(httpx.ReadTimeout(""), operation="agent run")
        == "ReadTimeout during agent run"
    )
    assert (
        claude_agent._error_text(RuntimeError("boom"), operation="agent run")
        == "RuntimeError during agent run: boom"
    )


@pytest.mark.asyncio
async def test_steering_echo_becomes_a_delivered_event() -> None:
    agent = _ActiveAgent()
    agent.accepted_steering_ids.add("steer-1")
    echo = UserMessage(content="also check refunds", uuid="steer-1")
    unrelated = UserMessage(content="the run prompt", uuid="prompt-1")
    client = FakeClient([unrelated, echo, _result()])
    await asyncio.wait_for(
        _relay_sdk_messages(client, agent, agent.event_queue, _SdkStreamState()),
        timeout=5,
    )
    events = _drain(agent.event_queue)
    assert [(e.type, e.content) for e in events if e.type != "done"] == [
        ("steering_delivered", "steer-1")
    ]
