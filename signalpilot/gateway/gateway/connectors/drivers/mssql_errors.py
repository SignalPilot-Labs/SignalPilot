"""Readable SQL Server error text for agents and users.

pymssql renders an error as ``(207, b"Invalid column name 'x'.DB-Lib error
message 20018, severity 16:\\nGeneral SQL Server error: Check messages from
the SQL Server\\n...")``: a tuple repr whose useful sentence is followed by
FreeTDS boilerplate. Error text is capped before it reaches the agent, so the
boilerplate crowds out the part that says what went wrong.
"""

from __future__ import annotations

import re

# FreeTDS appends "DB-Lib error message <n>, severity <n>:" blocks after the
# server's own message. Everything from the first block on is boilerplate.
_DBLIB_TAIL = re.compile(r"\s*DB-Lib error message \d+.*\Z", re.DOTALL)


def sql_server_error_text(exc: BaseException) -> str:
    """``SQL Server error 207: Invalid column name 'x'.`` for a pymssql error."""
    args = getattr(exc, "args", ())
    number = args[0] if args and isinstance(args[0], int) else None
    raw = args[1] if len(args) > 1 else (args[0] if args and number is None else str(exc))
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    message = _DBLIB_TAIL.sub("", str(raw)).strip() or str(exc)
    return f"SQL Server error {number}: {message}" if number is not None else f"SQL Server error: {message}"
