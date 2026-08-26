"""Private S3 facade for workspace blobs, manifests, and snapshots.

The boto3 client is injectable so hermetic tests can hand in a moto-backed
client; production resolves configuration from the environment once and caches
the facade process-wide.
"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any


class WorkspaceStorageUnavailable(RuntimeError):
    pass


class WorkspaceObjectStorage:
    def __init__(self, *, bucket: str | None = None, client: Any | None = None) -> None:
        self.bucket = (bucket if bucket is not None else os.getenv("SP_WORKSPACE_S3_BUCKET", "")).strip()
        self.endpoint = os.getenv("SP_WORKSPACE_S3_ENDPOINT", "").strip() or None
        self.region = os.getenv("SP_WORKSPACE_S3_REGION", "").strip() or None
        self.access_key = os.getenv("SP_WORKSPACE_S3_ACCESS_KEY", "").strip() or None
        self.secret_key = os.getenv("SP_WORKSPACE_S3_SECRET_KEY", "").strip() or None
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.bucket)

    def _require_client(self):
        if not self.enabled:
            raise WorkspaceStorageUnavailable(
                "Workspace object storage is not configured (SP_WORKSPACE_S3_BUCKET)"
            )
        if self._client is None:
            import boto3
            from botocore.config import Config

            # Pool must cover the store's upload concurrency (Semaphore(32) in
            # WorkspaceStore) or bulk imports churn connections.
            kwargs: dict[str, Any] = {
                "config": Config(signature_version="s3v4", max_pool_connections=64)
            }
            if self.endpoint:
                kwargs["endpoint_url"] = self.endpoint
            if self.region:
                kwargs["region_name"] = self.region
            if self.access_key:
                kwargs["aws_access_key_id"] = self.access_key
            if self.secret_key:
                kwargs["aws_secret_access_key"] = self.secret_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    async def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        client = self._require_client()
        await asyncio.to_thread(
            client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get_bytes(self, key: str) -> bytes | None:
        client = self._require_client()

        def _read() -> bytes | None:
            try:
                response = client.get_object(Bucket=self.bucket, Key=key)
            except client.exceptions.NoSuchKey:
                return None
            except Exception as exc:  # botocore surfaces 404s as ClientError too
                if _is_missing_key_error(exc):
                    return None
                raise
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        client = self._require_client()

        def _head() -> bool:
            try:
                client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception as exc:
                if _is_missing_key_error(exc):
                    return False
                raise

        return await asyncio.to_thread(_head)

    async def head_size(self, key: str) -> int | None:
        client = self._require_client()

        def _head() -> int | None:
            try:
                response = client.head_object(Bucket=self.bucket, Key=key)
            except Exception as exc:
                if _is_missing_key_error(exc):
                    return None
                raise
            return int(response.get("ContentLength") or 0)

        return await asyncio.to_thread(_head)

    async def delete_prefix(self, prefix: str) -> int:
        client = self._require_client()

        def _delete() -> int:
            deleted = 0
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix.rstrip("/") + "/"):
                keys = [{"Key": item["Key"]} for item in page.get("Contents") or []]
                for start in range(0, len(keys), 1000):
                    batch = keys[start : start + 1000]
                    if batch:
                        client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch, "Quiet": True})
                        deleted += len(batch)
            return deleted

        return await asyncio.to_thread(_delete)

    async def presign_get(self, key: str, *, expires_seconds: int = 600) -> str:
        client = self._require_client()
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(30, min(3600, expires_seconds)),
        )

    async def presign_put(self, key: str, *, expires_seconds: int = 600) -> str:
        client = self._require_client()
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(30, min(3600, expires_seconds)),
        )


def _is_missing_key_error(exc: Exception) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return code in {"404", "NoSuchKey", "NotFound"}


@lru_cache(maxsize=1)
def workspace_object_storage() -> WorkspaceObjectStorage:
    return WorkspaceObjectStorage()


def reset_workspace_object_storage() -> None:
    workspace_object_storage.cache_clear()
