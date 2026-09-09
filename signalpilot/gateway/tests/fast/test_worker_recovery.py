from gateway.standalone_chat.worker_recovery import INTERRUPTED_SUMMARY, interrupted_tool_completions


def test_open_calls_close_children_first_then_spawns():
    events = [
        ("tool_started", {"tool": "TodoWrite", "tool_call_id": "p1"}),
        ("tool_completed", {"tool": "TodoWrite", "tool_call_id": "p1", "error": False}),
        ("tool_started", {"tool": "Agent", "tool_call_id": "a1"}),
        ("tool_started", {"tool": "Agent", "tool_call_id": "a2"}),
        ("tool_started", {"tool": "Bash", "tool_call_id": "c1", "parent_tool_call_id": "a1"}),
        ("tool_completed", {"tool": "Bash", "tool_call_id": "c1", "parent_tool_call_id": "a1", "error": False}),
        ("tool_started", {"tool": "mcp__signalpilot__query_database", "tool_call_id": "c2", "parent_tool_call_id": "a2"}),
        ("tool_started", {"tool": "Read", "tool_call_id": "orphan"}),
        ("tool_started", {"tool": "NoId"}),
    ]
    closing = interrupted_tool_completions(events)
    assert [(c["tool_call_id"], c.get("parent_tool_call_id")) for c in closing] == [
        ("c2", "a2"), ("a1", None), ("a2", None), ("orphan", None),
    ]
    assert closing[0]["tool"] == "mcp__signalpilot__query_database"
    assert all(c["error"] is False and c["interrupted"] is True and c["summary"] == INTERRUPTED_SUMMARY for c in closing)


def test_nothing_open_yields_nothing():
    assert interrupted_tool_completions([]) == []
    assert interrupted_tool_completions([
        ("tool_started", {"tool": "Read", "tool_call_id": "r"}),
        ("tool_completed", {"tool": "Read", "tool_call_id": "r"}),
    ]) == []
