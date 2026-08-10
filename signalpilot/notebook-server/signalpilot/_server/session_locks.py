from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class SessionConnectionLocks:
    """Provide independent connection locks for notebook file keys."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @contextmanager
    def hold(self, file_key: str) -> Iterator[None]:
        """Hold the connection lock for one notebook file."""
        with self._guard:
            lock = self._locks.setdefault(file_key, threading.Lock())
        with lock:
            yield
