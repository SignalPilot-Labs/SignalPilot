"""Queue and Kernel managers for session management.

Standard implementations (QueueManagerImpl, KernelManagerImpl):
    Use multiprocessing.Process for edit mode and threading.Thread for run mode.
    Communicate via multiprocessing or threading queues.

IPC implementations (IPCQueueManagerImpl, IPCKernelManagerImpl):
    Launch kernel as subprocess with ZeroMQ IPC.
    Each notebook gets its own sandboxed virtual environment.
"""

from signalpilot._session.managers.errors import KernelStartupError
from signalpilot._session.managers.factory import create_kernel_and_queues
from signalpilot._session.managers.ipc import (
    IPCKernelManagerImpl,
    IPCQueueManagerImpl,
)
from signalpilot._session.managers.kernel import KernelManagerImpl
from signalpilot._session.managers.queue import QueueManagerImpl
from signalpilot._session.managers.warmup import preload_kernel_modules

__all__ = [
    "IPCKernelManagerImpl",
    "IPCQueueManagerImpl",
    "KernelManagerImpl",
    "KernelStartupError",
    "QueueManagerImpl",
    "create_kernel_and_queues",
    "preload_kernel_modules",
]
