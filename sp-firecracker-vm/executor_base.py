"""
Abstract base for sandbox executors.

All executors (Firecracker, gVisor) implement this interface so the
sandbox manager can swap backends without changing the HTTP layer.
"""

import abc


RESULT_KEYS = ("success", "output", "error", "exit_code", "vm_id", "execution_ms")


class ExecutorBase(abc.ABC):
    """Contract every sandbox executor must fulfill."""

    @abc.abstractmethod
    async def start(self) -> None:
        """One-time initialization (snapshot creation, image pull, etc.)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def execute(self, code: str, timeout: int) -> dict:
        """Run untrusted code and return a result dict.

        Required keys in the returned dict:
            success      (bool)  — True if exit_code == 0
            output       (str)   — captured stdout
            error        (str|None) — captured stderr or error message
            exit_code    (int)   — process exit code
            vm_id        (str)   — unique execution identifier
            execution_ms (float) — wall-clock time in milliseconds
        """
        raise NotImplementedError

    @abc.abstractmethod
    def health(self) -> dict:
        """Return a JSON-serialisable health status dict."""
        raise NotImplementedError

    @abc.abstractmethod
    def cleanup_vm(self, vm_id: str) -> None:
        """Force-kill and clean up a specific execution."""
        raise NotImplementedError

    @abc.abstractmethod
    def list_vms(self) -> list[dict]:
        """Return list of currently active executions."""
        raise NotImplementedError
