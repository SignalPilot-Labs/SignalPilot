"""Tiny console logging helpers used by all dbt benchmark runners."""

from __future__ import annotations

import time
from typing import TextIO


_log_file: TextIO | None = None


def set_log_file(fh: TextIO) -> None:
    """Set the module-level file handle for tee logging."""
    global _log_file
    _log_file = fh


def close_log_file() -> None:
    """Flush and close the log file handle, reset to None. Idempotent."""
    global _log_file
    if _log_file is not None:
        _log_file.flush()
        _log_file.close()
        _log_file = None


def log(msg: str, level: str = "INFO") -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    if _log_file is not None:
        _log_file.write(line + "\n")
        _log_file.flush()


def log_separator(title: str = "") -> None:
    sep = f"\n{'='*60}"
    print(sep, flush=True)
    if _log_file is not None:
        _log_file.write(sep + "\n")
        _log_file.flush()
    if title:
        titled = f"  {title}"
        sep2 = f"{'='*60}"
        print(titled, flush=True)
        print(sep2, flush=True)
        if _log_file is not None:
            _log_file.write(titled + "\n")
            _log_file.write(sep2 + "\n")
            _log_file.flush()
