# Copyright 2026 SignalPilot. All rights reserved.
"""Session management for sp server.

This module provides session management functionality including:
- Session lifecycle (creation, resumption, closure)
- Kernel management (process/thread management, interruption)
- Queue management (control, completion, input queues)
- Room management (broadcasting to multiple consumers)
- File change handling

All public APIs are re-exported from this module for backward compatibility.
"""

from __future__ import annotations

from signalpilot._session.types import (
    KernelManager,
    QueueManager,
    Session,
)
from signalpilot._session.utils import send_message_to_consumer

__all__ = [
    "KernelManager",
    "QueueManager",
    "Session",
    "send_message_to_consumer",
]
