# Copyright 2026 SignalPilot. All rights reserved.
"""Internal API for session management."""

from signalpilot._internal.session import extensions
from signalpilot._session.model import SessionMode
from signalpilot._session.queue import ProcessLike
from signalpilot._session.state.session_view import SessionView
from signalpilot._session.types import KernelManager, QueueManager, Session

__all__ = [
    "KernelManager",
    "ProcessLike",
    "QueueManager",
    "Session",
    "SessionMode",
    "SessionView",
    "extensions",
]
