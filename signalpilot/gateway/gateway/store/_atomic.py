"""Atomic file creation helper."""

from __future__ import annotations

import os
from pathlib import Path


def _atomic_create_file(path: Path, content: bytes, mode: int = 0o600) -> bytes:
    """Atomically create a file with content.

    Uses O_CREAT | O_EXCL which is POSIX-atomic: exactly one process wins the
    creation race. If the file already exists, the existing content is returned.
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
        return content
    except FileExistsError:
        return path.read_bytes()
