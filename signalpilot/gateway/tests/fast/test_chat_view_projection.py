from gateway.agent_execution.chat_view_service import EVENT_FIELDS, project_event


def test_tool_started_keeps_only_display_fields_and_derives_label():
    payload = {
        "tool": "mcp__signalpilot__query_database",
        "tool_call_id": "call_1",
        "input": {"sql": "select 1", "description": "  Checking the   date range of rpt_daily_profitability. "},
    }
    projected = project_event("tool_started", payload)
    assert projected == {
        "tool": "mcp__signalpilot__query_database",
        "tool_call_id": "call_1",
        "label": "Checking the date range of rpt_daily_profitability.",
    }


def test_label_is_capped_and_absent_for_other_tools():
    long = "x" * 500
    projected = project_event("tool_started", {"tool": "query_database", "input": {"description": long}})
    assert len(projected["label"]) == 140
    assert "label" not in project_event("tool_started", {"tool": "Read", "input": {"description": long}})
    assert "label" not in project_event("tool_started", {"tool": "query_database", "input": "not a dict"})


def test_tool_completed_exposes_summary_but_never_results():
    payload = {
        "tool": "query_database",
        "summary": "1,204 rows · 0.4 s",
        "result": {"kind": "table", "rows": [[1]]},
        "result_text": "secret",
        "error": None,
    }
    assert project_event("tool_completed", payload) == {
        "tool": "query_database", "summary": "1,204 rows · 0.4 s", "error": None,
    }
    assert "summary" not in project_event("tool_completed", {"tool": "x", "summary": {"not": "text"}})


def test_thinking_delta_is_exposed_without_extra_fields():
    assert "thinking_delta" in EVENT_FIELDS
    assert project_event("thinking_delta", {"delta": "hm", "signature": "abc"}) == {"delta": "hm"}


def test_todo_write_exposes_plan_items_only():
    payload = {
        "tool": "TodoWrite",
        "input": {"todos": [
            {"content": "  Scan   project ", "status": "completed", "activeForm": "Scanning project"},
            {"content": "Build mart", "status": "in_progress"},
            {"content": "Verify", "status": "weird"},
            "not a dict",
            {"content": "   ", "status": "pending"},
        ], "secret": "x"},
    }
    assert project_event("tool_started", payload) == {
        "tool": "TodoWrite",
        "plan": [
            {"content": "Scan project", "status": "completed", "active": "Scanning project"},
            {"content": "Build mart", "status": "in_progress"},
            {"content": "Verify", "status": "pending"},
        ],
    }
    assert "plan" not in project_event("tool_started", {"tool": "TodoWrite", "input": {"todos": "nope"}})
