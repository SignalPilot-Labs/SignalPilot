"""Queue and Kernel managers for session management.

This module contains the infrastructure components for managing
kernel processes/threads and their associated communication queues.

Standard implementations (QueueManagerImpl, KernelManagerImpl):
    Use multiprocessing.Process for edit mode and threading.Thread for run mode.
    Communicate via multiprocessing or threading queues.

IPC implementations (IPCQueueManagerImpl, IPCKernelManagerImpl):
    Launch kernel as subprocess with ZeroMQ IPC.
    Each notebook gets its own sandboxed virtual environment.
"""

from signalpilot._session.managers.ipc import (
    IPCKernelManagerImpl,
    IPCQueueManagerImpl,
)
from signalpilot._session.managers.kernel import KernelManagerImpl
from signalpilot._session.managers.queue import QueueManagerImpl

__all__ = [
    "IPCKernelManagerImpl",
    "IPCQueueManagerImpl",
    "KernelManagerImpl",
    "QueueManagerImpl",
]
