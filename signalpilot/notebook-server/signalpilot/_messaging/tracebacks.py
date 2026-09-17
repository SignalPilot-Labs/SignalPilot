from __future__ import annotations

import html
import re
import sys

from signalpilot._messaging.cell_output import CellChannel, CellOutput
from signalpilot._messaging.context import is_code_mode_request
from signalpilot._messaging.notification import CellNotification
from signalpilot._messaging.notification_utils import broadcast_notification
from signalpilot._messaging.types import Stderr
from signalpilot._runtime.context.types import safe_get_context
from signalpilot._runtime.context.utils import get_mode


def _highlight_traceback(traceback: str) -> str:
    """
    Highlight the traceback with color.
    """

    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import PythonTracebackLexer

    formatter = HtmlFormatter()

    body = highlight(traceback, PythonTracebackLexer(), formatter)
    return f'<span class="codehilite">{body}</span>'


def _show_tracebacks_enabled() -> bool:
    """Returns True if show_tracebacks is enabled in the current config."""
    from signalpilot._runtime.context.types import (
        ContextNotInitializedError,
        get_context,
    )

    try:
        ctx = get_context()
        return bool(ctx.signalpilot_config["runtime"].get("show_tracebacks", False))
    except ContextNotInitializedError:
        return True  # no context → not in run mode, always show


def write_traceback(traceback: str) -> None:
    in_run_mode = get_mode() == "run"
    code_mode = is_code_mode_request()

    if isinstance(sys.stderr, Stderr) and not code_mode:
        # In run mode, only forward to the frontend if show_tracebacks is on.
        if in_run_mode and not _show_tracebacks_enabled():
            return
        # Strip sp's internal executor.py frame and highlight for the UI
        trimmed = _trim_traceback(traceback)
        sys.stderr._write_with_mimetype(
            _highlight_traceback(trimmed),
            mimetype="application/vnd.sp+traceback",
        )
    else:
        # When stderr is not redirected (e.g., run mode with redirect_console_to_browser=False),
        # send the traceback directly via the stream to ensure exceptions reach the frontend
        ctx = safe_get_context()
        if ctx is not None and ctx.cell_id is not None:
            # In run mode, only forward to the frontend if show_tracebacks is on.
            if in_run_mode and not _show_tracebacks_enabled():
                sys.stderr.write(traceback)
                return
            trimmed = _trim_traceback(traceback)
            broadcast_notification(
                CellNotification(
                    cell_id=ctx.cell_id,
                    console=CellOutput(
                        channel=CellChannel.STDERR,
                        mimetype="application/vnd.sp+traceback",
                        data=trimmed
                        if code_mode
                        else _highlight_traceback(trimmed),
                    ),
                ),
                ctx.stream,
            )
        else:
            # Fallback to regular stderr if no context is available
            sys.stderr.write(traceback)


def _trim_traceback(traceback: str) -> str:
    """
    Skip first DefaultExecutor.execute_cell traceback item which all traces start with.
    """

    lines = traceback.split("\n")
    if (
        len(lines) > 2
        and lines[0] == "Traceback (most recent call last):"
        and ('/signalpilot/_runtime/executor.py", line ' in lines[1] or '/signalpilot/_runtime/executor.py", line ' in lines[1])
        and lines[1].endswith(", in execute_cell")
    ):
        for i in range(2, len(lines)):
            if lines[i].startswith("  File "):
                return "\n".join(lines[:1] + lines[i:])

    return traceback


def is_code_highlighting(value: str) -> bool:
    return 'class="codehilite"' in value


_HTML_TAG_RE = re.compile(r"<[^>]+>")
TRACEBACK_MIMETYPE = "application/vnd.sp+traceback"


def plain_traceback_text(
    value: str, *, frames: int = 3, max_chars: int = 600
) -> str:
    """Return a traceback as plain text: the last ``frames`` frames, no HTML.

    Accepts the Pygments HTML the kernel emits for the UI or a raw traceback
    string. Earlier frames are replaced by one summary line and the result is
    clipped from the front so the final exception line always survives.
    """
    text = value
    if "<" in text and ">" in text:
        text = html.unescape(_HTML_TAG_RE.sub("", text))
    lines = [line.rstrip() for line in text.strip().splitlines()]
    if not lines:
        return ""
    header: list[str] = []
    body = lines
    if lines[0].startswith("Traceback (most recent call last)"):
        header, body = [lines[0]], lines[1:]
    frame_starts = [
        index for index, line in enumerate(body) if line.startswith("  File ")
    ]
    if frames > 0 and len(frame_starts) > frames:
        omitted = len(frame_starts) - frames
        body = [
            f"  ... {omitted} earlier frame(s) omitted",
            *body[frame_starts[-frames] :],
        ]
    result = "\n".join([*header, *body])
    if max_chars > 0 and len(result) > max_chars:
        result = "..." + result[-(max_chars - 3) :]
    return result
