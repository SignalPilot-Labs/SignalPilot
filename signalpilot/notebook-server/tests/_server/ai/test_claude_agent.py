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
