"""Object keys and the storage facade for published dashboards.

Keys live in the chat objects bucket under the organization prefix:

    organizations/<sha256(org_id)[:24]>/dashboards/<dashboard_id>/versions/<version_id>/spec.json
    organizations/<sha256(org_id)[:24]>/dashboards/<dashboard_id>/versions/<version_id>/datasets/<name>.csv

Only SQL datasets are stored; static datasets stay inline in the spec.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from gateway.standalone_chat.object_storage import (
    ChatObjectStorage,
    StoredObject,
    chat_object_storage,
    organization_prefix,
)

from .datasets import CSV_CONTENT_TYPE

SPEC_CONTENT_TYPE = "application/json"
MAX_SPEC_BYTES = 5 * 1024 * 1024
MAX_DATASET_BYTES = 50 * 1024 * 1024


def dashboard_prefix(org_id: str, dashboard_id: str) -> str:
    return f"{organization_prefix(org_id)}/dashboards/{dashboard_id}"


def version_prefix(org_id: str, dashboard_id: str, version_id: str) -> str:
    return f"{dashboard_prefix(org_id, dashboard_id)}/versions/{version_id}"


def spec_key(org_id: str, dashboard_id: str, version_id: str) -> str:
    return f"{version_prefix(org_id, dashboard_id, version_id)}/spec.json"


def dataset_key(org_id: str, dashboard_id: str, version_id: str, name: str) -> str:
    return f"{version_prefix(org_id, dashboard_id, version_id)}/datasets/{name}.csv"


class ObjectStore(Protocol):
    """The subset of ChatObjectStorage the dashboard domain uses."""

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject: ...

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes: ...

    async def delete_prefix(self, prefix: str) -> int: ...


class DashboardStorage:
    """Typed helpers over the shared object store."""

    def __init__(self, backend: ObjectStore | None = None) -> None:
        self._backend = backend

    @property
    def backend(self) -> ObjectStore:
        if self._backend is None:
            self._backend = chat_object_storage()
        return self._backend

    async def put_spec(self, key: str, spec: dict[str, Any]) -> StoredObject:
        data = json.dumps(spec, ensure_ascii=False, indent=2).encode("utf-8")
        return await self.backend.put_bytes(key=key, data=data, content_type=SPEC_CONTENT_TYPE)

    async def get_spec(self, key: str) -> dict[str, Any]:
        data = await self.backend.get_bytes(key, max_bytes=MAX_SPEC_BYTES)
        spec = json.loads(data.decode("utf-8-sig"))
        if not isinstance(spec, dict):
            raise ValueError("Stored dashboard spec is not an object")
        return spec

    async def put_dataset(self, key: str, data: bytes) -> StoredObject:
        return await self.backend.put_bytes(key=key, data=data, content_type=CSV_CONTENT_TYPE)

    async def get_dataset(self, key: str) -> bytes:
        return await self.backend.get_bytes(key, max_bytes=MAX_DATASET_BYTES)

    async def get_chat_object(self, key: str, *, max_bytes: int) -> bytes:
        """Bytes of a conversation file (the publish source) from the same bucket."""
        return await self.backend.get_bytes(key, max_bytes=max_bytes)

    async def delete_dashboard(self, org_id: str, dashboard_id: str) -> int:
        return await self.backend.delete_prefix(dashboard_prefix(org_id, dashboard_id))


def dashboard_storage(backend: ChatObjectStorage | None = None) -> DashboardStorage:
    return DashboardStorage(backend)
