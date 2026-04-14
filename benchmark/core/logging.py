"""Tiny console logging helpers used by all dbt benchmark runners.

Supports per-task log files via ContextVar for safe use under asyncio.gather.
Each asyncio.Task gets its own isolated log file handle automatically.
"""

from __future__ import annotations

import contextvars
import time
from pathlib import Path
from typing import IO

# Per-task log file handle. ContextVar gives each asyncio.Task its own value,
# preventing task A from writing to task B's log file when tasks yield control
# at await points. Do NOT replace with a module-level variable.
_log_file: contextvars.ContextVar[IO[str] | None] = contextvars.ContextVar(
    "_log_file", default=None
)


def set_log_file(path: Path) -> contextvars.Token:
    """Open a log file for append and bind it to the current task context.

    Returns a token that must be passed to close_log_file() to restore state.
    """
    handle: IO[str] = open(path, "a")  # noqa: WPS515 — intentional open without 'with'
    return _log_file.set(handle)


def close_log_file(token: contextvars.Token) -> None:
    """Close the current task's log file and restore the previous context value."""
    handle = _log_file.get()
    if handle is not None:
        handle.close()
    _log_file.reset(token)


def log(msg: str, level: str = "INFO") -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    fh = _log_file.get()
    if fh is not None:
        fh.write(line + "\n")
        fh.flush()


def log_separator(title: str = "") -> None:
    sep_line = f"\n{'='*60}"
    print(sep_line, flush=True)
    fh = _log_file.get()
    if fh is not None:
        fh.write(sep_line + "\n")
        fh.flush()
    if title:
        title_line = f"  {title}"
        eq_line = f"{'='*60}"
        print(title_line, flush=True)
        print(eq_line, flush=True)
        if fh is not None:
            fh.write(title_line + "\n")
            fh.write(eq_line + "\n")
            fh.flush()
