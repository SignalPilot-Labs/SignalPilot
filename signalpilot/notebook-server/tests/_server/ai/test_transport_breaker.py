"""Transport breaker: signatures, backoff, the terminal flag and the hooks."""

from __future__ import annotations

from typing import Any

import pytest

from signalpilot._server.ai import transport_breaker as tb


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    tb._BREAKERS.clear()
    yield
    tb._BREAKERS.clear()


@pytest.mark.parametrize(
    "response",
    [
        "Streamable HTTP error: connection closed",
        {"content": [{"type": "text", "text": "Session not found"}], "isError": True},
        "<html>502 Bad Gateway</html>",
        '{"jsonrpc":"2.0","error":{"code":-32600,"message":"bad"}}',
    ],
)
def test_transport_signatures_are_detected(response: Any) -> None:
    assert tb.is_transport_failure(response)


def test_ordinary_results_are_not_transport_failures() -> None:
    assert not tb.is_transport_failure("Query error: relation x does not exist")
    assert not tb.is_transport_failure({"rows": [{"a": 1}]})
    assert not tb.is_transport_failure(None)


def test_backoff_grows_and_trips_after_three_failures() -> None:
    breaker = tb.breaker_for_run("run-1")
    assert breaker.deny_reason(now=0.0) is None

    breaker.record_result("502 Bad Gateway", now=0.0)
    assert breaker.consecutive_failures == 1
    assert breaker.deny_reason(now=0.0) == (
        "SignalPilot gateway unavailable; wait 2 s then retry"
    )
    assert breaker.deny_reason(now=2.5) is None
    assert not tb.transport_unavailable("run-1")

    breaker.record_result("Session not found", now=3.0)
    assert breaker.deny_reason(now=3.0) == (
        "SignalPilot gateway unavailable; wait 5 s then retry"
    )
    assert breaker.deny_reason(now=4.5).endswith("wait 4 s then retry")

    breaker.record_result("Streamable HTTP error", now=10.0)
    assert breaker.consecutive_failures == 3
    assert breaker.transport_unavailable is True
    assert tb.transport_unavailable("run-1")
    reason = breaker.deny_reason(now=100.0)
    assert reason is not None
    assert reason.startswith(
        "SignalPilot gateway unavailable after 3 transport failures"
    )
    assert tb.gateway_unavailable_error("run-1") == {
        "public_error_code": "gateway_unavailable",
        "public_error_message": tb.GATEWAY_UNAVAILABLE_MESSAGE,
        "consecutive_failures": 3,
        "last_failure": "Streamable HTTP error",
    }


def test_a_successful_result_resets_the_counter() -> None:
    breaker = tb.breaker_for_run("run-2")
    breaker.record_result("502 Bad Gateway", now=0.0)
    breaker.record_result("502 Bad Gateway", now=0.0)
    assert breaker.record_result({"rows": []}, now=0.0) is False
    assert breaker.consecutive_failures == 0
    assert breaker.deny_reason(now=0.0) is None
    breaker.record_result("502 Bad Gateway", now=20.0)
    assert breaker.deny_reason(now=20.0).endswith("wait 2 s then retry")


def test_registry_reset_and_clear() -> None:
    breaker = tb.breaker_for_run("run-3")
    breaker.record_result("-32600")
    assert tb.breaker_for_run("run-3") is breaker
    assert tb.breaker_for_run("run-3", reset=True) is not breaker
    assert tb.gateway_unavailable_error("run-3") is None
    tb.clear_breaker("run-3")
    assert not tb.transport_unavailable("run-3")
    assert tb.gateway_unavailable_error("missing") is None


def _hooks(run_key: str) -> tuple[Any, Any]:
    hooks = tb.build_transport_breaker_hooks(run_key)
    pre = hooks["PreToolUse"][0].hooks[0]
    post = hooks["PostToolUse"][0].hooks[0]
    return pre, post


def _pre_input(tool: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {},
        "tool_use_id": "t1",
    }


def _post_input(tool: str, response: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "tool_input": {},
        "tool_response": response,
        "tool_use_id": "t1",
    }


@pytest.mark.asyncio
async def test_hooks_deny_gateway_tools_while_open_and_stop_when_tripped() -> None:
    pre, post = _hooks("run-h")
    tool = "mcp__signalpilot__query_database"
    ctx = {"signal": None}

    assert await pre(_pre_input(tool), "t1", ctx) == {}
    assert await post(_post_input(tool, "502 Bad Gateway"), "t1", ctx) == {}

    denied = await pre(_pre_input(tool), "t2", ctx)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied["hookSpecificOutput"]["permissionDecisionReason"] == (
        "SignalPilot gateway unavailable; wait 2 s then retry"
    )
    assert "continue_" not in denied
    # Built-in and notebook tools are never denied.
    assert await pre(_pre_input("Bash"), "t3", ctx) == {}
    assert await pre(_pre_input("mcp__signalpilot-notebook__run_cells"), "t4", ctx) == {}

    await post(_post_input("mcp__standalone-chat__inspect_dbt", "Session not found"), "t5", ctx)
    await post(_post_input(tool, {"isError": True, "content": "-32600"}), "t6", ctx)
    assert tb.transport_unavailable("run-h")

    stopped = await pre(_pre_input(tool), "t7", ctx)
    assert stopped["continue_"] is False
    assert stopped["stopReason"].startswith(
        "SignalPilot gateway unavailable after 3 transport failures"
    )
    assert stopped["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.asyncio
async def test_post_tool_use_failure_counts_the_error_text() -> None:
    hooks = tb.build_transport_breaker_hooks("run-f")
    failure = hooks["PostToolUseFailure"][0].hooks[0]
    await failure(
        {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "mcp__signalpilot__list_tables",
            "tool_input": {},
            "tool_use_id": "t1",
            "error": "Streamable HTTP error: 502",
        },
        "t1",
        {"signal": None},
    )
    assert tb.breaker_for_run("run-f").consecutive_failures == 1
    # A clean result on a non-gateway tool does not touch the counter.
    post = hooks["PostToolUse"][0].hooks[0]
    await post(_post_input("Bash", "ok"), "t2", {"signal": None})
    assert tb.breaker_for_run("run-f").consecutive_failures == 1
