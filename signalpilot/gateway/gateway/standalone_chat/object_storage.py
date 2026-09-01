"""Private S3-compatible storage for chat runtime payloads."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, BinaryIO

_KEY_PART_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _key_part(value: str, *, fallback: str) -> str:
    cleaned = _KEY_PART_RE.sub("-", value.strip()).strip("-.")
    return (cleaned or fallback)[:160]


def organization_prefix(org_id: str) -> str:
    digest = hashlib.sha256(org_id.encode("utf-8")).hexdigest()[:24]
    return f"organizations/{digest}"


def conversation_prefix(org_id: str, conversation_id: str) -> str:
    return f"{organization_prefix(org_id)}/conversations/{_key_part(conversation_id, fallback='conversation')}"


def runtime_object_key(
    *,
    org_id: str,
    conversation_id: str,
    run_id: str,
    category: str,
    object_id: str,
    filename: str,
) -> str:
    return (
        f"{conversation_prefix(org_id, conversation_id)}"
        f"/runs/{_key_part(run_id, fallback='run')}"
        f"/{_key_part(category, fallback='objects')}"
        f"/{_key_part(object_id, fallback='object')}-{_key_part(filename, fallback='payload')}"
    )


def conversation_file_key(
    *,
    org_id: str,
    conversation_id: str,
    file_id: str,
    filename: str,
) -> str:
    """Key for one durable conversation file under the conversation prefix."""
    return (
        f"{conversation_prefix(org_id, conversation_id)}"
        f"/files/{_key_part(file_id, fallback='file')}-{_key_part(filename, fallback='payload')}"
    )


@dataclass(frozen=True)
class StoredObject:
    key: str
    byte_size: int
    content_hash: str


class ObjectStorageUnavailable(RuntimeError):
    pass


class ChatObjectStorage:
    """Small async facade around a private boto3 S3 client."""

    def __init__(self) -> None:
        self.bucket = os.getenv("SP_CHAT_OBJECTS_BUCKET", "").strip()
        self.endpoint = os.getenv("SP_CHAT_OBJECTS_S3_ENDPOINT", "").strip() or None
        self.region = os.getenv("SP_CHAT_OBJECTS_S3_REGION", "").strip() or None
        self.access_key = os.getenv("SP_CHAT_OBJECTS_S3_ACCESS_KEY", "").strip() or None
        self.secret_key = os.getenv("SP_CHAT_OBJECTS_S3_SECRET_KEY", "").strip() or None
        self._client: Any | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.bucket)

    def _require_client(self):
        if not self.enabled:
            raise ObjectStorageUnavailable("Chat runtime object storage is not configured")
        if self._client is None:
            import boto3
            from botocore.config import Config

            kwargs: dict[str, Any] = {
                "config": Config(signature_version="s3v4"),
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

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        client = self._require_client()
        digest = hashlib.sha256(data).hexdigest()
        await asyncio.to_thread(
            client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={"sha256": digest},
        )
        return StoredObject(key=key, byte_size=len(data), content_hash=digest)

    async def put_file(self, *, key: str, fileobj: BinaryIO, content_type: str) -> StoredObject:
        data = await asyncio.to_thread(fileobj.read)
        if not isinstance(data, bytes):
            raise TypeError("Object payload must be bytes")
        return await self.put_bytes(key=key, data=data, content_type=content_type)

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
        client = self._require_client()

        def _read() -> bytes:
            response = client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                data = body.read(None if max_bytes is None else max_bytes + 1)
            finally:
                body.close()
            if max_bytes is not None and len(data) > max_bytes:
                raise ValueError("Stored object exceeds the permitted read size")
            return data

        return await asyncio.to_thread(_read)

    def iter_bytes(self, key: str, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        client = self._require_client()
        response = client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            while chunk := body.read(chunk_size):
                yield chunk
        finally:
            body.close()

    async def delete(self, key: str) -> None:
        client = self._require_client()
        await asyncio.to_thread(client.delete_object, Bucket=self.bucket, Key=key)

    async def copy(self, *, source_key: str, destination_key: str) -> StoredObject:
        """Copy one private object without exposing or materializing its payload."""
        client = self._require_client()

        def _copy() -> StoredObject:
            client.copy_object(
                Bucket=self.bucket,
                Key=destination_key,
                CopySource={"Bucket": self.bucket, "Key": source_key},
                MetadataDirective="COPY",
            )
            head = client.head_object(Bucket=self.bucket, Key=destination_key)
            digest = str((head.get("Metadata") or {}).get("sha256") or "")
            return StoredObject(
                key=destination_key,
                byte_size=int(head.get("ContentLength") or 0),
                content_hash=digest,
            )

        return await asyncio.to_thread(_copy)

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

    async def presign_get(self, key: str, *, expires_seconds: int = 300) -> str:
        client = self._require_client()
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=min(300, max(30, expires_seconds)),
        )

    async def presign_put(self, key: str, *, expires_seconds: int = 3600) -> str:
        client = self._require_client()
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=min(3600, max(30, expires_seconds)),
        )

    async def multipart_writer(self, *, key: str, content_type: str) -> MultipartUploadWriter:
        writer = MultipartUploadWriter(
            client=self._require_client(),
            bucket=self.bucket,
            key=key,
            content_type=content_type,
        )
        await asyncio.to_thread(writer.start)
        return writer


class MultipartUploadWriter(io.RawIOBase):
    """Seek-free file-like sink that uploads compressed Parquet bytes in parts."""

    _MIN_PART_BYTES = 8 * 1024 * 1024

    def __init__(self, *, client: Any, bucket: str, key: str, content_type: str) -> None:
        super().__init__()
        self.client = client
        self.bucket = bucket
        self.key = key
        self.content_type = content_type
        self.upload_id: str | None = None
        self.parts: list[dict[str, Any]] = []
        self.buffer = bytearray()
        self.position = 0
        self.digest = hashlib.sha256()
        self._completed = False

    def start(self) -> None:
        response = self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=self.key,
            ContentType=self.content_type,
        )
        self.upload_id = str(response["UploadId"])

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self.position

    def write(self, value: bytes | bytearray | memoryview) -> int:
        if self.upload_id is None or self._completed:
            raise ValueError("Multipart writer is not open")
        data = bytes(value)
        self.buffer.extend(data)
        self.digest.update(data)
        self.position += len(data)
        while len(self.buffer) >= self._MIN_PART_BYTES:
            self._upload_part(bytes(self.buffer[: self._MIN_PART_BYTES]))
            del self.buffer[: self._MIN_PART_BYTES]
        return len(data)

    def _upload_part(self, data: bytes) -> None:
        assert self.upload_id is not None
        part_number = len(self.parts) + 1
        response = self.client.upload_part(
            Bucket=self.bucket,
            Key=self.key,
            UploadId=self.upload_id,
            PartNumber=part_number,
            Body=data,
        )
        self.parts.append({"PartNumber": part_number, "ETag": response["ETag"]})

    def complete(self) -> StoredObject:
        if self.upload_id is None or self._completed:
            raise ValueError("Multipart writer is not open")
        if self.buffer or not self.parts:
            self._upload_part(bytes(self.buffer))
            self.buffer.clear()
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=self.key,
            UploadId=self.upload_id,
            MultipartUpload={"Parts": self.parts},
        )
        self._completed = True
        return StoredObject(
            key=self.key,
            byte_size=self.position,
            content_hash=self.digest.hexdigest(),
        )

    def abort(self) -> None:
        if self.upload_id is not None and not self._completed:
            self.client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=self.key,
                UploadId=self.upload_id,
            )
            self._completed = True


@lru_cache(maxsize=1)
def chat_object_storage() -> ChatObjectStorage:
    return ChatObjectStorage()


def reset_chat_object_storage() -> None:
    chat_object_storage.cache_clear()
