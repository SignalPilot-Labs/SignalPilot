"""Notebook orchestrator — manages compute pods for user notebook sessions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PodInfo:
    name: str
    ip: str | None
    status: str  # "pending", "running", "succeeded", "failed", "unknown"
    # internal_ip: raw pod IP used by the gateway proxy to reach the pod inside
    # the cluster. The gateway proxy routes to this address (pod_ip mode only).
    internal_ip: str | None = None


class NotebookOrchestrator(ABC):
    """Abstract interface for notebook pod lifecycle management."""

    @abstractmethod
    async def create_pod(
        self,
        *,
        pod_name: str,
        user_id: str,
        org_id: str,
        project_id: str | None,
        branch: str,
        image: str,
        gateway_url: str,
        session_jwt_secret_name: str,
        session_id: str,
        access_token: str | None,
    ) -> PodInfo:
        ...

    @abstractmethod
    async def ensure_namespace(self, org_id: str) -> str:
        """Idempotently create the org's tenant namespace. Returns the namespace name."""
        ...

    @abstractmethod
    async def delete_pod(self, pod_name: str, *, org_id: str) -> bool:
        ...

    @abstractmethod
    async def get_pod(self, pod_name: str, *, org_id: str) -> PodInfo | None:
        ...

    @abstractmethod
    async def wait_for_ready(self, pod_name: str, *, org_id: str, timeout: int = 60) -> PodInfo:
        ...

    @abstractmethod
    async def is_pod_alive(self, pod_name: str, *, org_id: str) -> bool:
        """Return True iff the pod exists and its phase is 'running'."""
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


__all__ = ["NotebookOrchestrator", "PodInfo"]
