"""Notebook orchestrator — manages compute pods for user notebook sessions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PodInfo:
    name: str
    ip: str | None
    status: str  # "pending", "running", "succeeded", "failed", "unknown"


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
        api_key: str | None,
        access_token: str | None = None,
    ) -> PodInfo:
        ...

    @abstractmethod
    async def delete_pod(self, pod_name: str) -> bool:
        ...

    @abstractmethod
    async def get_pod(self, pod_name: str) -> PodInfo | None:
        ...

    @abstractmethod
    async def wait_for_ready(self, pod_name: str, timeout: int = 60) -> PodInfo:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


__all__ = ["NotebookOrchestrator", "PodInfo"]
