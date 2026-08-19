"""Provider-agnostic interface for ephemeral sandbox VMs.

Improvement runs execute untrusted project code (dbt compiles third-party
Jinja) inside an isolated, disposable VM. The gateway talks to the VM through
this interface only, so the concrete provider (Vercel Sandbox today, an
AWS-backed runtime for on-prem deployments later) is swappable without
touching callers.

Handles are plain string ids: providers must support stateless reattach so a
sandbox created by one worker process can be driven or destroyed by another.
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


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


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

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> None: ...

    async def read_file(self, sandbox_id: str, path: str) -> bytes | None:
        """Return file contents, or None when the path does not exist."""
        ...

    async def destroy(self, sandbox_id: str) -> None:
        """Stop and delete the sandbox. Idempotent: missing ids are ignored."""
        ...
