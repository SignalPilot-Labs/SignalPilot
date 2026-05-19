"""Org-scoped S3 client for the gateway."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _validate_path(path: str) -> str:
    if ".." in path or path.startswith("/"):
        raise ValueError(f"Invalid path: {path}")
    return path.strip("/")


class S3Client:
    """Org-scoped S3 wrapper. All keys are prefixed with {org_id}/."""

    def __init__(self, boto_client: Any, bucket: str, org_id: str):
        self._client = boto_client
        self._bucket = bucket
        self._org_id = org_id

    def _key(self, path: str) -> str:
        return f"{self._org_id}/{_validate_path(path)}"

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def put_object(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if len(data) > _MAX_FILE_SIZE:
            raise ValueError(f"File too large: {len(data)} bytes (max {_MAX_FILE_SIZE})")
        key = self._key(path)
        await self._run(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    async def get_object(self, path: str) -> bytes:
        key = self._key(path)
        try:
            resp = await self._run(self._client.get_object, Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except self._client.exceptions.NoSuchKey:
            raise FileNotFoundError(f"Object not found: {path}")

    async def delete_object(self, path: str) -> bool:
        key = self._key(path)
        await self._run(self._client.delete_object, Bucket=self._bucket, Key=key)
        return True

    async def list_objects(self, prefix: str = "", max_keys: int = 1000) -> list[dict]:
        full_prefix = self._key(prefix) if prefix else f"{self._org_id}/"
        if not full_prefix.endswith("/"):
            full_prefix += "/"
        resp = await self._run(
            self._client.list_objects_v2,
            Bucket=self._bucket,
            Prefix=full_prefix,
            MaxKeys=max_keys,
        )
        items = []
        for obj in resp.get("Contents", []):
            rel_key = obj["Key"][len(f"{self._org_id}/"):]
            items.append({
                "key": rel_key,
                "size": obj["Size"],
                "last_modified": obj["LastModified"].timestamp(),
            })
        return items

    async def delete_prefix(self, prefix: str) -> int:
        objects = await self.list_objects(prefix, max_keys=1000)
        if not objects:
            return 0
        delete_keys = [{"Key": self._key(obj["key"])} for obj in objects]
        await self._run(
            self._client.delete_objects,
            Bucket=self._bucket,
            Delete={"Objects": delete_keys},
        )
        return len(delete_keys)

    async def head_object(self, path: str) -> dict | None:
        key = self._key(path)
        try:
            resp = await self._run(self._client.head_object, Bucket=self._bucket, Key=key)
            return {
                "size": resp["ContentLength"],
                "last_modified": resp["LastModified"].timestamp(),
                "content_type": resp.get("ContentType"),
            }
        except Exception:
            return None
