"""Internal API for inter-process communication (IPC)."""

from signalpilot._ipc.connection import Channel, Connection
from signalpilot._ipc.queue_manager import QueueManager
from signalpilot._ipc.types import ConnectionInfo, KernelArgs

__all__ = [
    "Channel",
    "Connection",
    "ConnectionInfo",
    "KernelArgs",
    "QueueManager",
]
