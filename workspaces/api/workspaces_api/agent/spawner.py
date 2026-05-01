"""Spawner Protocol and StubSpawner for the Workspaces API.

Contract: a real implementation (R3+) must:
  - Mint a gateway run token (HMAC of run_id + connector_id, TTL = run lifetime)
  - Allocate a free dbt-proxy host port
  - Build the sandbox env (inference token, MCP key, dbt-proxy config)
  - Start the gvisor container via Docker SDK or subprocess

TODO(round-3): real gvisor spawn — replace StubSpawner with a concrete implementation.

Token non-leakage:
  InferenceBundle.__repr__ masks oauth_token and api_key. Tests in
  tests/test_spawner.py format a log line and assert the token is absent.
  There is NO runtime assert in StubSpawner.spawn — that invariant is
  test-time only; production code does not pay for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from workspaces_api.agent.inference import InferenceBundle


@dataclass(frozen=True)
class SpawnRequest:
    """Immutable description of a container spawn intent."""

    run_id: uuid.UUID
    workspace_id: str
    prompt: str
    inference: InferenceBundle
    gateway_run_token: str | None
    dbt_proxy_host_port: int | None

    def __repr__(self) -> str:
        token_marker = "***" if self.gateway_run_token else "None"
        return (
            f"SpawnRequest(run_id={self.run_id!r}, workspace_id={self.workspace_id!r}, "
            f"prompt=<{len(self.prompt)} chars>, inference={self.inference!r}, "
            f"gateway_run_token={token_marker}, dbt_proxy_host_port={self.dbt_proxy_host_port!r})"
        )


class Spawner(Protocol):
    """Protocol for run spawners. Implementations must be async-safe."""

    async def spawn(self, request: SpawnRequest) -> None:
        """Spawn a sandbox container for the given run request."""
        ...


class StubSpawner:
    """Records spawn intent in memory. No subprocess, no container.

    Used in unit tests and local dev runs where no gvisor runtime is available.
    """

    def __init__(self) -> None:
        self.calls: list[SpawnRequest] = []

    async def spawn(self, request: SpawnRequest) -> None:
        """Append the spawn request to the in-memory call log."""
        self.calls.append(request)
