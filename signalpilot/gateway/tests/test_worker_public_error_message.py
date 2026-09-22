"""public_error_message never shows a raw exception repr to the user.

Plan section B: the archive upload timeout used to surface as ``ReadTimeout('')``
in the assistant reply. Known runtime failures map to fixed sentences; raw text
stays in the trace and raw_error fields.
"""

from __future__ import annotations

import httpx
import pytest

from gateway.standalone_chat.worker_errors import (
    AnalysisRuntimeError,
    public_error_message,
    public_full_trace,
    public_raw_error_fields,
)


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://runtime.internal/execute")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


class TestKnownRuntimeExceptions:
    def test_read_timeout_default_operation(self):
        assert public_error_message(httpx.ReadTimeout("")) == "The analysis runtime timed out while finishing the run"

    def test_timeout_with_operation_context(self):
        message = public_error_message(httpx.TimeoutException(""), operation="uploading the notebook archive")
        assert message == "The analysis runtime timed out while uploading the notebook archive"

    @pytest.mark.parametrize("code", [500, 502, 413])
    def test_http_status_error_names_the_code(self, code):
        assert public_error_message(_http_status_error(code)) == f"The analysis runtime returned HTTP {code}"

    @pytest.mark.parametrize("exc", [ConnectionError("refused"), httpx.ConnectError("[Errno 111]")])
    def test_connection_errors(self, exc):
        assert public_error_message(exc) == "Could not reach the analysis runtime"

    def test_empty_message_names_type_and_operation(self):
        assert public_error_message(RuntimeError(""), operation="archiving") == "RuntimeError during archiving"


class TestForwardedRuntimeErrors:
    """The worker wraps the runtime's error event text in AnalysisRuntimeError."""

    def test_plain_sentence_is_kept(self):
        assert public_error_message(AnalysisRuntimeError("The notebook kernel was lost")) == "The notebook kernel was lost"

    def test_repr_of_timeout_is_mapped(self):
        message = public_error_message(AnalysisRuntimeError("ReadTimeout('')"), operation="uploading the archive")
        assert message == "The analysis runtime timed out while uploading the archive"
        assert "ReadTimeout('')" not in message

    def test_repr_of_http_status_error_extracts_the_code(self):
        error = AnalysisRuntimeError("HTTPStatusError('Server error 502 Bad Gateway for url ...')")
        assert public_error_message(error) == "The analysis runtime returned HTTP 502"

    def test_repr_of_unknown_type_is_named_not_shown(self):
        error = AnalysisRuntimeError("SomethingOdd('internal detail')")
        assert public_error_message(error) == "SomethingOdd during finishing the run"

    def test_empty_forwarded_error(self):
        assert public_error_message(AnalysisRuntimeError("")) == "AnalysisRuntimeError during finishing the run"

    def test_raw_text_survives_in_trace_and_raw_error(self):
        error = AnalysisRuntimeError("ReadTimeout('')", full_trace="ReadTimeout('')\nTraceback ...")
        assert "ReadTimeout('')" in public_full_trace(error)
        assert public_raw_error_fields(error)["raw_error"] == "ReadTimeout('')"


class TestGenericExceptions:
    def test_first_line_only_and_redacted(self):
        error = RuntimeError("Database failed: postgresql://admin:hunter2@db.internal/prod\nTraceback (most recent call last):")
        message = public_error_message(error)
        assert message == "Database failed: [REDACTED_CONNECTION]"
        assert "hunter2" not in message

    def test_traceback_only_text_is_not_shown(self):
        error = RuntimeError("Traceback (most recent call last):\n  File x")
        assert public_error_message(error) == "RuntimeError during finishing the run"

    def test_str_is_never_returned_raw_for_repr_shaped_text(self):
        error = RuntimeError("ValueError('secret internals')")
        assert public_error_message(error) == "ValueError during finishing the run"
