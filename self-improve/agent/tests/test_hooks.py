"""Unit tests for agent/hooks.py — tool call hooks and subagent lifecycle tracking.

Covers:
- get_stuck_subagents: empty state, idle detection, stale cleanup
- set_run_id / set_agent_role: global state setters
- pre_tool_use_hook: no-op when run_id unset, last-tool tracking, timeout blocking
- post_tool_use_hook: no-op when run_id unset, duration calculation
- subagent_start_hook: start time recording
- subagent_stop_hook: tracking cleanup and transcript parsing
- _safe_serialize: str / dict / list / non-serializable objects
"""

import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out agent.db before the module is loaded.
# We also need to ensure hooks_module.db always points at our mock, even when
# other test modules in the same session have loaded the real db module.
# ---------------------------------------------------------------------------
_db_mock = MagicMock()
_db_mock.log_tool_call = AsyncMock(return_value=None)
_db_mock.log_audit = AsyncMock(return_value=None)
sys.modules.setdefault("agent.db", _db_mock)

# Make the agent package importable from the tests sub-directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hooks as hooks_module  # noqa: E402
from hooks import (  # noqa: E402
    get_stuck_subagents,
    set_run_id,
    set_agent_role,
    pre_tool_use_hook,
    post_tool_use_hook,
    subagent_start_hook,
    subagent_stop_hook,
    _safe_serialize,
    SUBAGENT_TIMEOUT_SEC,
    SUBAGENT_IDLE_KILL_SEC,
)

# Point the module's own `db` name at our mock unconditionally.
# This survives other test files loading the real db module into sys.modules.
hooks_module.db = _db_mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset all module-level globals and re-apply db mock before every test."""
    # Re-attach mock in case something swapped it out during the session
    hooks_module.db = _db_mock
    hooks_module._subagent_start_times.clear()
    hooks_module._subagent_last_tool.clear()
    hooks_module._pre_tool_times.clear()
    hooks_module._run_id = None
    hooks_module._agent_role = "worker"
    # Reset db mock call counts
    _db_mock.log_tool_call.reset_mock()
    _db_mock.log_audit.reset_mock()
    yield
    hooks_module._subagent_start_times.clear()
    hooks_module._subagent_last_tool.clear()
    hooks_module._pre_tool_times.clear()
    hooks_module._run_id = None
    hooks_module._agent_role = "worker"


# ---------------------------------------------------------------------------
# get_stuck_subagents
# ---------------------------------------------------------------------------

def test_get_stuck_subagents_empty_returns_empty_list():
    """get_stuck_subagents returns an empty list when no subagents are tracked."""
    result = get_stuck_subagents()
    assert result == []


def test_get_stuck_subagents_active_agent_not_stuck(monkeypatch):
    """An agent that called a tool recently is not considered stuck."""
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    hooks_module._subagent_start_times["agent-1"] = now - 60  # started 1 min ago
    hooks_module._subagent_last_tool["agent-1"] = now - 30    # tool 30 s ago

    result = get_stuck_subagents()
    assert result == []


def test_get_stuck_subagents_idle_agent_returned(monkeypatch):
    """An agent idle longer than SUBAGENT_IDLE_KILL_SEC is included in results."""
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    start = now - (SUBAGENT_IDLE_KILL_SEC + 120)      # started well before threshold
    last_tool = now - (SUBAGENT_IDLE_KILL_SEC + 60)   # last tool just over threshold
    hooks_module._subagent_start_times["agent-idle"] = start
    hooks_module._subagent_last_tool["agent-idle"] = last_tool

    result = get_stuck_subagents()
    assert len(result) == 1
    entry = result[0]
    assert entry["agent_id"] == "agent-idle"
    assert entry["idle_seconds"] >= SUBAGENT_IDLE_KILL_SEC
    assert entry["total_seconds"] >= SUBAGENT_IDLE_KILL_SEC + 120


def test_get_stuck_subagents_no_last_tool_uses_start_time(monkeypatch):
    """When no last-tool time exists, start time is used as the idle baseline."""
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    # Start time far enough back to be idle but not stale
    start = now - (SUBAGENT_IDLE_KILL_SEC + 30)
    hooks_module._subagent_start_times["agent-no-tool"] = start
    # No entry in _subagent_last_tool

    result = get_stuck_subagents()
    assert len(result) == 1
    assert result[0]["agent_id"] == "agent-no-tool"


def test_get_stuck_subagents_stale_agent_cleaned_up(monkeypatch):
    """An agent past 2x the absolute timeout is removed from tracking dicts."""
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    stale_start = now - (SUBAGENT_TIMEOUT_SEC * 2 + 1)
    hooks_module._subagent_start_times["agent-stale"] = stale_start
    hooks_module._subagent_last_tool["agent-stale"] = stale_start + 5

    result = get_stuck_subagents()

    # Stale agent must NOT appear in stuck list
    assert all(e["agent_id"] != "agent-stale" for e in result)
    # Must be removed from both dicts
    assert "agent-stale" not in hooks_module._subagent_start_times
    assert "agent-stale" not in hooks_module._subagent_last_tool


def test_get_stuck_subagents_multiple_agents_mixed(monkeypatch):
    """Only agents exceeding idle threshold (but not stale) are returned."""
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)

    # Active agent — should be ignored
    hooks_module._subagent_start_times["active"] = now - 60
    hooks_module._subagent_last_tool["active"] = now - 30

    # Stuck agent — should be returned
    hooks_module._subagent_start_times["stuck"] = now - (SUBAGENT_IDLE_KILL_SEC + 300)
    hooks_module._subagent_last_tool["stuck"] = now - (SUBAGENT_IDLE_KILL_SEC + 120)

    # Stale agent — should be cleaned up
    hooks_module._subagent_start_times["stale"] = now - (SUBAGENT_TIMEOUT_SEC * 2 + 1)

    result = get_stuck_subagents()
    agent_ids = [e["agent_id"] for e in result]
    assert "stuck" in agent_ids
    assert "active" not in agent_ids
    assert "stale" not in agent_ids
    assert "stale" not in hooks_module._subagent_start_times


# ---------------------------------------------------------------------------
# set_run_id / set_agent_role
# ---------------------------------------------------------------------------

def test_set_run_id_updates_global():
    """set_run_id changes the module-level _run_id."""
    assert hooks_module._run_id is None
    set_run_id("run-abc-123")
    assert hooks_module._run_id == "run-abc-123"


def test_set_run_id_overwrites_previous():
    """Calling set_run_id twice replaces the first value."""
    set_run_id("first-run")
    set_run_id("second-run")
    assert hooks_module._run_id == "second-run"


def test_set_agent_role_updates_global():
    """set_agent_role changes the module-level _agent_role."""
    set_agent_role("ceo")
    assert hooks_module._agent_role == "ceo"


def test_set_agent_role_default_is_worker():
    """The default agent role is 'worker'."""
    assert hooks_module._agent_role == "worker"


# ---------------------------------------------------------------------------
# pre_tool_use_hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_noop_without_run_id():
    """pre_tool_use_hook returns {} without calling db when _run_id is None."""
    result = await pre_tool_use_hook(
        {"tool_name": "Bash", "tool_input": {}}, "tu-1", {}
    )
    assert result == {}
    _db_mock.log_tool_call.assert_not_called()


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_logs_tool_call(monkeypatch):
    """pre_tool_use_hook calls db.log_tool_call with expected arguments."""
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-xyz")

    await pre_tool_use_hook(
        {"tool_name": "Read", "tool_input": {"file": "/tmp/x"}, "session_id": "sess-1"},
        "tu-abc",
        {},
    )

    _db_mock.log_tool_call.assert_called_once()
    call_kwargs = _db_mock.log_tool_call.call_args.kwargs
    assert call_kwargs["run_id"] == "run-xyz"
    assert call_kwargs["phase"] == "pre"
    assert call_kwargs["tool_name"] == "Read"
    assert call_kwargs["tool_use_id"] == "tu-abc"
    assert call_kwargs["session_id"] == "sess-1"


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_records_timestamp_for_duration(monkeypatch):
    """pre_tool_use_hook stores the current time keyed by tool_use_id."""
    now = 5_555_555.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-1")

    await pre_tool_use_hook({"tool_name": "Bash", "tool_input": {}}, "tu-timing", {})

    assert hooks_module._pre_tool_times.get("tu-timing") == now


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_no_timestamp_without_tool_use_id(monkeypatch):
    """pre_tool_use_hook does not store a timestamp when tool_use_id is None."""
    set_run_id("run-1")
    await pre_tool_use_hook({"tool_name": "Bash", "tool_input": {}}, None, {})
    assert len(hooks_module._pre_tool_times) == 0


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_tracks_subagent_last_tool(monkeypatch):
    """pre_tool_use_hook updates _subagent_last_tool for agent_id calls."""
    now = 9_999_999.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-1")

    await pre_tool_use_hook(
        {"tool_name": "Bash", "tool_input": {}, "agent_id": "sub-agent-7"},
        "tu-1",
        {},
    )

    assert hooks_module._subagent_last_tool.get("sub-agent-7") == now


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_blocks_on_timeout(monkeypatch):
    """pre_tool_use_hook returns a block decision when subagent exceeds 45-min timeout."""
    set_run_id("run-timeout")
    start_t = 1_000_000.0
    # Advance time past the absolute timeout
    now = start_t + SUBAGENT_TIMEOUT_SEC + 1
    monkeypatch.setattr(time, "time", lambda: now)
    hooks_module._subagent_start_times["agent-slow"] = start_t

    result = await pre_tool_use_hook(
        {"tool_name": "Bash", "tool_input": {}, "agent_id": "agent-slow"},
        "tu-block",
        {},
    )

    assert result.get("decision") == "block"
    assert "reason" in result
    assert str(SUBAGENT_TIMEOUT_SEC) in result["reason"]


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_logs_timeout_audit(monkeypatch):
    """pre_tool_use_hook calls db.log_audit when a subagent times out."""
    set_run_id("run-audit")
    start_t = 1_000_000.0
    now = start_t + SUBAGENT_TIMEOUT_SEC + 5
    monkeypatch.setattr(time, "time", lambda: now)
    hooks_module._subagent_start_times["agent-audit"] = start_t

    await pre_tool_use_hook(
        {"tool_name": "Read", "tool_input": {}, "agent_id": "agent-audit"},
        "tu-audit",
        {},
    )

    _db_mock.log_audit.assert_called_once()
    call_args = _db_mock.log_audit.call_args
    assert call_args.args[1] == "subagent_timeout"


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_no_block_under_timeout(monkeypatch):
    """pre_tool_use_hook does NOT block when elapsed time is under the timeout."""
    set_run_id("run-ok")
    start_t = 1_000_000.0
    now = start_t + SUBAGENT_TIMEOUT_SEC - 1   # one second under limit
    monkeypatch.setattr(time, "time", lambda: now)
    hooks_module._subagent_start_times["agent-ok"] = start_t

    result = await pre_tool_use_hook(
        {"tool_name": "Read", "tool_input": {}, "agent_id": "agent-ok"},
        "tu-ok",
        {},
    )

    assert result.get("decision") != "block"


@pytest.mark.asyncio(loop_scope="function")
async def test_pre_tool_use_hook_returns_empty_dict_normally(monkeypatch):
    """pre_tool_use_hook returns {} under normal (non-blocking) conditions."""
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-normal")

    result = await pre_tool_use_hook({"tool_name": "Bash", "tool_input": {}}, "tu-1", {})
    assert result == {}


# ---------------------------------------------------------------------------
# post_tool_use_hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_post_tool_use_hook_noop_without_run_id():
    """post_tool_use_hook returns {} without calling db when _run_id is None."""
    result = await post_tool_use_hook(
        {"tool_name": "Bash", "tool_response": "output"}, "tu-1", {}
    )
    assert result == {}
    _db_mock.log_tool_call.assert_not_called()


@pytest.mark.asyncio(loop_scope="function")
async def test_post_tool_use_hook_calculates_duration(monkeypatch):
    """post_tool_use_hook computes duration_ms from pre_tool_times entry."""
    pre_time = 1_000_000.0
    post_time = pre_time + 1.5  # 1500 ms later

    call_count = [0]

    def fake_time():
        call_count[0] += 1
        return post_time

    monkeypatch.setattr(time, "time", fake_time)
    set_run_id("run-dur")
    hooks_module._pre_tool_times["tu-dur"] = pre_time

    await post_tool_use_hook(
        {"tool_name": "Bash", "tool_response": "done"},
        "tu-dur",
        {},
    )

    call_kwargs = _db_mock.log_tool_call.call_args.kwargs
    assert call_kwargs["duration_ms"] == 1500


@pytest.mark.asyncio(loop_scope="function")
async def test_post_tool_use_hook_removes_pre_tool_time_entry(monkeypatch):
    """post_tool_use_hook pops the tool_use_id from _pre_tool_times after use."""
    now = 2_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-pop")
    hooks_module._pre_tool_times["tu-pop"] = now - 0.1

    await post_tool_use_hook({"tool_name": "Read", "tool_response": "data"}, "tu-pop", {})

    assert "tu-pop" not in hooks_module._pre_tool_times


@pytest.mark.asyncio(loop_scope="function")
async def test_post_tool_use_hook_duration_none_without_pre_entry(monkeypatch):
    """post_tool_use_hook passes duration_ms=None when no pre-hook timestamp exists."""
    now = 2_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-no-pre")

    await post_tool_use_hook(
        {"tool_name": "Bash", "tool_response": "output"},
        "tu-no-pre",
        {},
    )

    call_kwargs = _db_mock.log_tool_call.call_args.kwargs
    assert call_kwargs["duration_ms"] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_post_tool_use_hook_logs_correct_phase(monkeypatch):
    """post_tool_use_hook logs with phase='post'."""
    now = 3_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-phase")

    await post_tool_use_hook({"tool_name": "Write", "tool_response": "ok"}, "tu-p", {})

    call_kwargs = _db_mock.log_tool_call.call_args.kwargs
    assert call_kwargs["phase"] == "post"


@pytest.mark.asyncio(loop_scope="function")
async def test_post_tool_use_hook_returns_empty_dict(monkeypatch):
    """post_tool_use_hook always returns {}."""
    now = 3_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-ret")

    result = await post_tool_use_hook({"tool_name": "Bash"}, "tu-r", {})
    assert result == {}


# ---------------------------------------------------------------------------
# subagent_start_hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_start_hook_noop_without_run_id():
    """subagent_start_hook returns {} without calling db when _run_id is None."""
    result = await subagent_start_hook({"agent_id": "a1"}, None, {})
    assert result == {}
    _db_mock.log_audit.assert_not_called()


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_start_hook_records_start_time(monkeypatch):
    """subagent_start_hook stores current time in _subagent_start_times."""
    now = 7_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-start")

    await subagent_start_hook({"agent_id": "sub-42"}, "tu-s", {})

    assert hooks_module._subagent_start_times.get("sub-42") == now


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_start_hook_logs_audit_event(monkeypatch):
    """subagent_start_hook calls db.log_audit with event_type='subagent_start'."""
    now = 7_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-start-audit")

    await subagent_start_hook({"agent_id": "sub-audit"}, "tu-sa", {})

    _db_mock.log_audit.assert_called_once()
    call_args = _db_mock.log_audit.call_args
    assert call_args.args[1] == "subagent_start"


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_start_hook_no_start_time_for_empty_agent_id(monkeypatch):
    """subagent_start_hook does not record a time when agent_id is empty."""
    now = 7_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    set_run_id("run-empty")

    await subagent_start_hook({"agent_id": ""}, "tu-empty", {})

    assert "" not in hooks_module._subagent_start_times


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_start_hook_returns_empty_dict(monkeypatch):
    """subagent_start_hook always returns {}."""
    monkeypatch.setattr(time, "time", lambda: 1.0)
    set_run_id("run-r")

    result = await subagent_start_hook({"agent_id": "a"}, "tu", {})
    assert result == {}


# ---------------------------------------------------------------------------
# subagent_stop_hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_noop_without_run_id():
    """subagent_stop_hook returns {} without calling db when _run_id is None."""
    hooks_module._subagent_start_times["a1"] = 1.0
    result = await subagent_stop_hook({"agent_id": "a1"}, None, {})
    assert result == {}
    _db_mock.log_audit.assert_not_called()


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_removes_start_time():
    """subagent_stop_hook removes the agent from _subagent_start_times."""
    set_run_id("run-stop")
    hooks_module._subagent_start_times["agent-stop"] = 1_000_000.0

    await subagent_stop_hook({"agent_id": "agent-stop"}, "tu-stop", {})

    assert "agent-stop" not in hooks_module._subagent_start_times


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_removes_last_tool():
    """subagent_stop_hook removes the agent from _subagent_last_tool."""
    set_run_id("run-stop-lt")
    hooks_module._subagent_start_times["agent-lt"] = 1_000_000.0
    hooks_module._subagent_last_tool["agent-lt"] = 1_000_100.0

    await subagent_stop_hook({"agent_id": "agent-lt"}, "tu-lt", {})

    assert "agent-lt" not in hooks_module._subagent_last_tool


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_logs_complete_audit():
    """subagent_stop_hook logs an audit event with event_type='subagent_complete'."""
    set_run_id("run-complete")

    await subagent_stop_hook({"agent_id": "agent-done"}, "tu-done", {})

    _db_mock.log_audit.assert_called_once()
    call_args = _db_mock.log_audit.call_args
    assert call_args.args[1] == "subagent_complete"


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_reads_transcript(tmp_path):
    """subagent_stop_hook extracts final_text from a valid JSONL transcript."""
    set_run_id("run-transcript")
    transcript = tmp_path / "transcript.jsonl"
    # Write a JSONL file with an assistant message containing text content
    line = json.dumps({
        "role": "assistant",
        "content": [{"type": "text", "text": "All done, here is the summary."}],
    })
    transcript.write_text(line + "\n", encoding="utf-8")

    await subagent_stop_hook(
        {"agent_id": "agent-tx", "agent_transcript_path": str(transcript)},
        "tu-tx",
        {},
    )

    call_args = _db_mock.log_audit.call_args
    details = call_args.args[2]
    assert "All done, here is the summary." in details["final_text"]


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_handles_missing_transcript():
    """subagent_stop_hook handles a nonexistent transcript path gracefully."""
    set_run_id("run-no-tx")

    # Should not raise; final_text will be empty
    result = await subagent_stop_hook(
        {"agent_id": "agent-no-tx", "agent_transcript_path": "/nonexistent/path.jsonl"},
        "tu-no-tx",
        {},
    )
    assert result == {}


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_no_transcript_path():
    """subagent_stop_hook works fine when no transcript_path is provided."""
    set_run_id("run-no-path")

    result = await subagent_stop_hook({"agent_id": "agent-np"}, None, {})
    assert result == {}
    call_args = _db_mock.log_audit.call_args
    details = call_args.args[2]
    assert details["final_text"] == ""
    assert details["has_transcript"] is False


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_reads_string_content_transcript(tmp_path):
    """subagent_stop_hook handles assistant messages with string (not list) content."""
    set_run_id("run-str-content")
    transcript = tmp_path / "tx.jsonl"
    line = json.dumps({"role": "assistant", "content": "Simple string output."})
    transcript.write_text(line + "\n", encoding="utf-8")

    await subagent_stop_hook(
        {"agent_id": "agent-sc", "agent_transcript_path": str(transcript)},
        "tu-sc",
        {},
    )

    call_args = _db_mock.log_audit.call_args
    details = call_args.args[2]
    assert "Simple string output." in details["final_text"]


@pytest.mark.asyncio(loop_scope="function")
async def test_subagent_stop_hook_returns_empty_dict():
    """subagent_stop_hook always returns {}."""
    set_run_id("run-ret")

    result = await subagent_stop_hook({"agent_id": "a"}, None, {})
    assert result == {}


# ---------------------------------------------------------------------------
# _safe_serialize
# ---------------------------------------------------------------------------

def test_safe_serialize_string_passthrough():
    """_safe_serialize returns strings unchanged."""
    assert _safe_serialize("hello world") == "hello world"


def test_safe_serialize_empty_string():
    """_safe_serialize returns an empty string unchanged."""
    assert _safe_serialize("") == ""


def test_safe_serialize_dict_recursively_serializes_values():
    """_safe_serialize recurses into dict values."""
    data = {"key": "value", "num": 42, "nested": {"inner": "x"}}
    result = _safe_serialize(data)
    assert result == {"key": "value", "num": 42, "nested": {"inner": "x"}}


def test_safe_serialize_list_recursively_serializes_items():
    """_safe_serialize recurses into list items."""
    data = ["a", 1, {"b": 2}]
    result = _safe_serialize(data)
    assert result == ["a", 1, {"b": 2}]


def test_safe_serialize_json_primitive_passthrough():
    """_safe_serialize passes through JSON-compatible primitives (int, float, bool, None)."""
    assert _safe_serialize(42) == 42
    assert _safe_serialize(3.14) == 3.14
    assert _safe_serialize(True) is True
    assert _safe_serialize(None) is None


def test_safe_serialize_non_serializable_converts_to_str():
    """_safe_serialize converts non-JSON-serializable objects to their str() representation."""

    class CustomObj:
        def __repr__(self):
            return "CustomObj()"

        def __str__(self):
            return "custom-object-str"

    result = _safe_serialize(CustomObj())
    assert result == "custom-object-str"


def test_safe_serialize_non_serializable_in_dict():
    """_safe_serialize converts non-serializable values nested inside a dict."""

    class Unserializable:
        def __str__(self):
            return "unserializable"

    result = _safe_serialize({"key": Unserializable()})
    assert result == {"key": "unserializable"}


def test_safe_serialize_non_serializable_in_list():
    """_safe_serialize converts non-serializable items nested inside a list."""

    class Opaque:
        def __str__(self):
            return "opaque"

    result = _safe_serialize([1, Opaque(), "text"])
    assert result == [1, "opaque", "text"]


def test_safe_serialize_result_is_json_encodable():
    """The output of _safe_serialize can always be encoded with json.dumps."""

    class Weird:
        def __str__(self):
            return "weird"

    data = {"a": Weird(), "b": [Weird(), 99], "c": "plain"}
    result = _safe_serialize(data)
    # Should not raise
    json.dumps(result)
