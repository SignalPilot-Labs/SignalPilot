from types import SimpleNamespace

from signalpilot._server.ai.claude_agent import _result_message_content


def test_result_message_content_preserves_sdk_error_details() -> None:
    message = SimpleNamespace(
        subtype="error_during_execution",
        stop_reason="authentication_error",
        result=None,
        errors=["OAuth token rejected", "Request ID: req_123"],
    )

    assert _result_message_content(message) == (
        "OAuth token rejected\n"
        "Request ID: req_123\n"
        "Claude Agent SDK result: subtype=error_during_execution, "
        "stop_reason=authentication_error"
    )


def test_result_message_content_uses_result_and_deduplicates_errors() -> None:
    message = SimpleNamespace(
        subtype="error_during_execution",
        stop_reason=None,
        result="Credit balance is too low",
        errors=["Credit balance is too low"],
    )

    assert _result_message_content(message) == (
        "Credit balance is too low\n"
        "Claude Agent SDK result: subtype=error_during_execution"
    )


def test_result_message_content_retains_max_turns_message() -> None:
    message = SimpleNamespace(
        subtype="error_max_turns",
        stop_reason=None,
        result=None,
        errors=None,
    )

    assert (
        _result_message_content(message)
        == "The agent reached its turn limit before completing."
    )


def test_result_message_content_has_actionable_empty_fallback() -> None:
    message = SimpleNamespace(
        subtype="",
        stop_reason=None,
        result=None,
        errors=None,
    )

    assert _result_message_content(message) == (
        "Claude Agent SDK returned an error without diagnostic details."
    )
