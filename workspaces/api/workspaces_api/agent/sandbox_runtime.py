"""Sandbox runtime adapter — wraps asyncio.create_subprocess_exec at spawn time.

Public surface:
  - SandboxRuntime (Protocol)
  - Mount (frozen dataclass)
  - NoneRuntime — direct exec, no sandbox wrapper
  - RunscRuntime — wraps argv under `runsc do` (gVisor)
  - build_runtime(settings) — factory, no I/O

Design notes (R8/R9):
  - RunscRuntime uses `runsc do` (unprivileged, no OCI bundle required).
  - runsc do flag shape (gvisor 20260323.0):
      -volume SRC[:DST]  (repeated per mount; no :ro suffix in this version)
  - Network: runsc do places the sandbox in its own netns (default IP 192.168.10.2).
    There is NO --net=host or --network flag on `runsc do`.
    TODO(round-9): Loopback dbt-proxy (127.0.0.1) is unreachable from within
    the sandbox. Options: (a) runsc run with OCI bundle + --network=host,
    or (b) expose proxy on a host-veth-reachable address. For R8, connector-
    bearing runs should NOT be started with SP_SANDBOX_RUNTIME=runsc; cloud
    deployments that use runsc must disable connector runs until R9.
  - Constructor accepts an optional _exec_fn for DI in tests.
    Default: asyncio.create_subprocess_exec. Never monkeypatched.
  - Only "runsc" is supported as a non-none runtime. "runc" is rejected at
    runtime via SandboxRuntimeUnavailable (config-shape is unchanged).
"""

from __future__ import annotations

import asyncio
import asyncio.subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from workspaces_api.errors import SandboxRuntimeUnavailable

if TYPE_CHECKING:
    from workspaces_api.config import Settings

# Type alias for the exec callable to support DI.
_ExecFn = Callable[..., Awaitable[Any]]

_RUNSC_VERSION_TIMEOUT = 5.0


@dataclass(frozen=True)
class Mount:
    """A bind-mount directive passed to the runtime adapter.

    source: host-side absolute path.
    target: container-side absolute path.
    readonly: whether the mount should be read-only.

    NOTE: runsc do -volume does not support a :ro suffix in gvisor 20260323.0.
    The readonly field is honoured by NoneRuntime (no-op) and is available for
    future runtimes that support it. RunscRuntime mounts all volumes read-write
    because the host FS is already globally read-only with overlay; the writable
    resume dir only needs a plain -volume entry.
    """

    source: Path
    target: PurePosixPath
    readonly: bool


class SandboxRuntime:
    """Protocol-style base class for runtime adapters.

    Subclasses must implement exec() and validate_available().
    """

    name: str

    async def exec(
        self,
        *,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        mounts: list[Mount],
        stdout: int,
        stderr: int,
    ) -> asyncio.subprocess.Process:
        raise NotImplementedError

    async def validate_available(self) -> None:
        raise NotImplementedError


class NoneRuntime(SandboxRuntime):
    """Direct asyncio.create_subprocess_exec — no sandboxing.

    Used for local development and tests. validate_available is a no-op.
    """

    name = "none"

    def __init__(self, _exec_fn: _ExecFn | None = None) -> None:
        self._exec_fn: _ExecFn = _exec_fn or asyncio.create_subprocess_exec

    async def exec(
        self,
        *,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        mounts: list[Mount],
        stdout: int,
        stderr: int,
    ) -> asyncio.subprocess.Process:
        proc = await self._exec_fn(
            *argv,
            env=env,
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
        )
        return proc  # type: ignore[return-value]

    async def validate_available(self) -> None:
        pass


class RunscRuntime(SandboxRuntime):
    """gVisor runsc do runtime adapter.

    Builds the `runsc do` argv for each spawn call.

    Flag shape for gvisor 20260323.0:
        runsc do [-volume SRC[:DST]] [other flags] -- <cmd> [args...]

    NOTE: -volume does not accept a :ro suffix in this gvisor version.
    All mounts are writable from runsc's perspective. The host FS is already
    globally readonly (runsc do default), so the only writable mount needed
    is the resume dir.

    TODO(round-9): No --net=host equivalent exists on `runsc do`. The sandbox
    runs in its own netns (default IP 192.168.10.2). The dbt-proxy at
    127.0.0.1:<port> is unreachable from within the sandbox. Connector-bearing
    runs must not be dispatched to a runsc-sandboxed spawner until R9 resolves
    the networking strategy (runsc run with OCI bundle + host network, or proxy
    on veth-accessible address).
    """

    name = "runsc"

    def __init__(
        self,
        binary: Path,
        _exec_fn: _ExecFn | None = None,
    ) -> None:
        self._binary = binary
        self._exec_fn: _ExecFn = _exec_fn or asyncio.create_subprocess_exec

    async def exec(
        self,
        *,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        mounts: list[Mount],
        stdout: int,
        stderr: int,
    ) -> asyncio.subprocess.Process:
        runsc_argv = [str(self._binary), "do"]
        for mount in mounts:
            volume_spec = f"{mount.source}:{mount.target}"
            runsc_argv += ["-volume", volume_spec]
        runsc_argv += ["--", *argv]

        proc = await self._exec_fn(
            *runsc_argv,
            env=env,
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
        )
        return proc  # type: ignore[return-value]

    async def validate_available(self) -> None:
        """Check that the runtime binary exists and responds to --version."""
        try:
            proc = await asyncio.create_subprocess_exec(
                str(self._binary),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=_RUNSC_VERSION_TIMEOUT)
            if proc.returncode != 0:
                raise SandboxRuntimeUnavailable(
                    f"sandbox runtime {self.name!r} binary {self._binary} "
                    f"exited with code {proc.returncode}"
                )
        except FileNotFoundError as exc:
            raise SandboxRuntimeUnavailable(
                f"sandbox runtime {self.name!r} binary not found: {self._binary}"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise SandboxRuntimeUnavailable(
                f"sandbox runtime {self.name!r} --version timed out"
            ) from exc


def build_runtime(settings: "Settings") -> SandboxRuntime:
    """Return the appropriate SandboxRuntime based on settings.

    Pure function — no I/O. Validation (binary availability) happens
    separately via runtime.validate_available() in the lifespan gate.

    Only "none" and "runsc" are valid at runtime. "runc" is rejected with
    SandboxRuntimeUnavailable so the lifespan handler surfaces a clear
    startup-crash log (consistent failure mode for "runtime cannot be used").
    """
    runtime_name = settings.sp_sandbox_runtime
    if runtime_name == "none":
        return NoneRuntime()
    if runtime_name == "runsc":
        return RunscRuntime(binary=settings.sp_runsc_binary)
    # Any other value (including "runc") is misconfiguration — reject loudly.
    raise SandboxRuntimeUnavailable(
        f"unknown SP_SANDBOX_RUNTIME: {runtime_name!r}"
    )
