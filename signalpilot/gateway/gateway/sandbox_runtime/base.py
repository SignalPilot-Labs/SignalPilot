"""Provider-agnostic interface for ephemeral sandbox VMs.

Two consumer shapes share this seam:

- Batch (eval tasks, improvement runs): create → exec-to-completion → destroy.
- Server (notebook sessions): create with exposed ports → start a long-running
  process → reach it over its public route URL → extend the execution grant
  while active → snapshot on idle → resume on return.

The concrete provider (Vercel Sandbox today) is swappable without touching
callers. Handles are plain string ids: providers must support stateless
reattach so a sandbox created by one worker process can be driven, snapshotted,
or destroyed by another — no in-process registries, ever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class SandboxRuntimeError(RuntimeError):
    """Base error for sandbox runtime failures."""


class SandboxNotFound(SandboxRuntimeError):
    """The sandbox id does not exist or has already been destroyed."""


@dataclass(frozen=True)
class GitCheckout:
    """Clone spec applied at sandbox creation. Credentials, when present,
    are short-lived (GitHub App installation tokens) and never logged."""

    url: str
    revision: str | None = None
    depth: int = 1
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class SandboxSpec:
    time_limit_seconds: int = 900
    env: dict[str, str] = field(default_factory=dict)
    git: GitCheckout | None = None
    tags: dict[str, str] = field(default_factory=dict)
    # Server-shape additions (Notebook Runtime v2):
    ports: tuple[int, ...] = ()
    image: str | None = None
    vcpus: int | None = None
    memory_mb: int | None = None
    persistent: bool = False
    # None = provider default (unrestricted). () = deny all egress. A
    # non-empty tuple allows exactly those domains (plus DNS).
    egress_allow_hosts: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class SandboxInfo:
    """Inventory row for reapers and panels."""

    sandbox_id: str
    status: str
    tags: dict[str, str] = field(default_factory=dict)
    snapshot_id: str | None = None
    # Epoch seconds; lets reapers grant newly created sandboxes a grace
    # window while their launch is still in flight.
    created_at_epoch: float | None = None


class SandboxRuntime(Protocol):
    """Async facade over one sandbox provider."""

    provider: str

    async def create(self, spec: SandboxSpec) -> str:
        """Create a sandbox and return its id."""
        ...

    async def exec(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecResult:
        """Run `command` through a shell inside the sandbox and wait for it."""
        ...

    async def start_process(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Start `command` without waiting; return a provider process id."""
        ...

    async def routes(self, sandbox_id: str) -> dict[int, str]:
        """Map each exposed port to its public HTTPS URL."""
        ...

    async def extend_time_limit(self, sandbox_id: str, seconds: int) -> None:
        """Extend the current execution grant by `seconds` (>= 1)."""
        ...

    async def snapshot(self, sandbox_id: str, *, expiration_seconds: int | None = None) -> str:
        """Snapshot the sandbox and return the snapshot id. The sandbox keeps
        running; pair with stop()/destroy() for scale-to-zero."""
        ...

    async def resume(self, sandbox_id: str) -> None:
        """Resume a stopped sandbox in place (same id)."""
        ...

    async def stop(self, sandbox_id: str) -> None:
        """Stop the active session without destroying the sandbox."""
        ...

    async def list(self, *, tags: dict[str, str] | None = None) -> list[SandboxInfo]:
        """Enumerate live sandboxes, optionally filtered by tag equality.
        This is the orphan reaper's primitive."""
        ...

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> None: ...

    async def read_file(self, sandbox_id: str, path: str) -> bytes | None:
        """Return file contents, or None when the path does not exist."""
        ...

    async def destroy(self, sandbox_id: str) -> None:
        """Stop and delete the sandbox. Idempotent: missing ids are ignored."""
        ...
