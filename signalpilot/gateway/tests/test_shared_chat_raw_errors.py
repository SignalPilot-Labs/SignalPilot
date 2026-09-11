from gateway.standalone_chat.worker_errors import AnalysisRuntimeError, public_raw_error_fields
from gateway.standalone_chat.worker_errors import public_error_message, public_full_trace


def test_shared_runtime_error_fields_preserve_original_details_and_flags(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "opaque-private-token")
    error = AnalysisRuntimeError("Failed", raw_error="Provider HTTP 401 opaque-private-token " + "x" * 9000,
                                 stderr="Authentication failed https://example.invalid/private", stderr_truncated=True)
    fields = public_raw_error_fields(error)
    assert fields["raw_error"].startswith("Provider HTTP 401")
    assert len(fields["raw_error"]) == 8192
    assert fields["raw_error_truncated"] and fields["stderr_truncated"]
    assert "Authentication failed" in fields["stderr"]
    assert "opaque-private-token" not in fields["raw_error"]
    assert "example.invalid" not in fields["stderr"]


def test_gateway_exception_has_original_error_without_fabricated_stderr():
    fields = public_raw_error_fields(ValueError("Workspace revision is missing"))
    assert fields == {"raw_error": "Workspace revision is missing", "stderr": "",
                      "raw_error_truncated": False, "stderr_truncated": False}


def test_quoted_secrets_with_spaces_are_redacted_in_all_shared_error_fields():
    message = '''Upstream failed {"password":"one two", "api_key": "three four"}'''
    error = AnalysisRuntimeError(message, full_trace=message, stderr=message)
    values = [public_error_message(error), public_full_trace(error),
              public_raw_error_fields(error)["raw_error"], public_raw_error_fields(error)["stderr"]]
    for value in values:
        assert "Upstream failed" in value
        for secret in ("one", "two", "three", "four"):
            assert secret not in value
