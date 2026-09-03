from types import SimpleNamespace

from signalpilot._server.ai.claude_agent import (
    _rate_limit_diagnostic,
    _result_message_content,
)


def test_result_message_content_preserves_sdk_error_details() -> None:
    message = SimpleNamespace(
        subtype="error_during_execution",
        stop_reason="authentication_error",
        result=None,
        errors=["OAuth token rejected", "Request ID: req_123"],
    )

    assert _result_message_content(message) == (
        "OAuth token rejected\nRequest ID: req_123"
    )


def test_result_message_content_uses_result_and_deduplicates_errors() -> None:
    message = SimpleNamespace(
        subtype="error_during_execution",
        stop_reason=None,
        result="Credit balance is too low",
        errors=["Credit balance is too low"],
    )

    assert _result_message_content(message) == "Credit balance is too low"


def test_result_message_content_does_not_invent_max_turns_message() -> None:
    message = SimpleNamespace(
        subtype="error_max_turns",
        stop_reason=None,
        result=None,
        errors=None,
    )

    assert _result_message_content(message) == repr(message)


def test_result_message_content_uses_raw_sdk_repr_when_text_is_empty() -> None:
    message = SimpleNamespace(
        subtype="",
        stop_reason=None,
        result=None,
        errors=None,
    )

    assert _result_message_content(message) == repr(message)


def test_rate_limit_diagnostic_preserves_raw_sdk_fields() -> None:
    raw = {
        "status": "rejected",
        "resetsAt": 1788213000,
        "rateLimitType": "five_hour",
        "unknownFutureField": "preserved",
    }
    info = SimpleNamespace(
        status="rejected",
        resets_at=1788213000,
        rate_limit_type="five_hour",
        utilization=1.0,
        overage_status="rejected",
        overage_resets_at=None,
        overage_disabled_reason="not_enabled",
        raw=raw,
    )

    assert _rate_limit_diagnostic(info) == {
        "status": "rejected",
        "resets_at": 1788213000,
        "rate_limit_type": "five_hour",
        "utilization": 1.0,
        "overage_status": "rejected",
        "overage_resets_at": None,
        "overage_disabled_reason": "not_enabled",
        "raw": raw,
    }


class TestToolResultText:
    """claude_agent_state.tool_result_text flattens SDK result content."""

    def test_none_and_str_pass_through(self) -> None:
        from signalpilot._server.ai.claude_agent_state import tool_result_text

        assert tool_result_text(None) == ""
        assert tool_result_text("plain") == "plain"

    def test_dict_blocks_join_text_and_mark_images(self) -> None:
        from signalpilot._server.ai.claude_agent_state import tool_result_text

        text = tool_result_text(
            [
                {"type": "text", "text": "line one"},
                {"type": "image", "source": {"data": "zzz"}},
                {"type": "text", "text": "line two"},
            ]
        )
        assert text == "line one\n[image]\nline two"
        assert "zzz" not in text

    def test_object_blocks_use_text_attribute(self) -> None:
        from signalpilot._server.ai.claude_agent_state import tool_result_text

        blocks = [SimpleNamespace(type="text", text='{"a": 1}')]
        assert tool_result_text(blocks) == '{"a": 1}'

    def test_other_dict_blocks_become_json_not_repr(self) -> None:
        from signalpilot._server.ai.claude_agent_state import tool_result_text

        text = tool_result_text([{"type": "tool_use", "name": "x"}])
        assert text == '{"type": "tool_use", "name": "x"}'
        assert "'type'" not in text

    def test_event_copy_is_capped_with_marker(self) -> None:
        from signalpilot._server.ai.claude_agent_state import (
            TOOL_RESULT_EVENT_MAX_CHARS,
            clip_tool_result_for_event,
        )

        raw = "x" * 100_000
        clipped = clip_tool_result_for_event(raw)
        marker = "…[event copy truncated: 34464 more chars]"
        assert clipped.endswith(marker)
        assert clipped[:TOOL_RESULT_EVENT_MAX_CHARS] == "x" * 65_536
        assert clip_tool_result_for_event("short") == "short"

    def test_agent_event_carries_result_chars(self) -> None:
        from signalpilot._server.ai.claude_agent_state import AgentEvent

        assert AgentEvent(type="tool_result").result_chars is None
        assert AgentEvent(type="tool_result", result_chars=7).result_chars == 7
