"""Sandbox-side capture of scratch files for one chat run.

The filesystem is the artifact API. Every file the agent saves under the run
scratch is swept at each tool boundary and pushed to the gateway.
"""

from __future__ import annotations

from signalpilot._server.api.endpoints.chat_files.capture import (
    CapturedFile,
    Fingerprint,
    ScratchFileCapture,
    is_captured_path,
)
from signalpilot._server.api.endpoints.chat_files.hooks import (
    build_after_tool_result_hook,
    capture_after_tool_result,
    capture_at_run_end,
    tool_is_read_only,
)
from signalpilot._server.api.endpoints.chat_files.uploader import (
    RuntimeFileUploader,
    UploadOutcome,
)

__all__ = [
    "CapturedFile",
    "Fingerprint",
    "RuntimeFileUploader",
    "ScratchFileCapture",
    "UploadOutcome",
    "build_after_tool_result_hook",
    "capture_after_tool_result",
    "capture_at_run_end",
    "is_captured_path",
    "tool_is_read_only",
]
