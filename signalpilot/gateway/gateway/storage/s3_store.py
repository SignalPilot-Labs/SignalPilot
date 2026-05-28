"""S3-backed workspace store — production backend.

Uses aioboto3 for async S3 access. All PUTs use ServerSideEncryption="AES256".

Layout:
    s3://<bucket>/<prefix_root>/
      org/<org_id>/
        user/<user_id>/
          notebook/<notebook_id>/
            snapshots/<version>/<relpath>
            _manifest.current.json

Atomic commit semantics (C2):
    1. Build PUT tasks for all data files under snapshots/<version>/.
    2. await asyncio.gather(*put_tasks)  ← MUST complete 2xx; on ANY failure, abort.
    3. ONLY after gather returns successfully: PUT _manifest.current.json.

This ensures every observed manifest pointer references a COMPLETE snapshot tree.
A partial snapshot is invisible — its pointer is never written.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aioboto3
from botocore.exceptions import ClientError

from . import manifest as manifest_mod
from .manifest import Manifest, deserialize, serialize
from .workspace_store import (
    MAX_FILE_BYTES,
    HydrateResult,
    SnapshotResult,
    WorkspaceKey,
    WorkspaceStore,
)

logger = logging.getLogger(__name__)

_MANIFEST_KEY = "_manifest.current.json"
_FORBIDDEN = {"..", ""}


def _check_part(part: str, label: str) -> None:
    """Reject path traversal: '..', empty, NUL, '/', backslash."""
    if part in _FORBIDDEN:
        raise ValueError(f"Invalid S3 key component ({label}): {part!r}")
    if "\x00" in part or "/" in part or "\\" in part:
        raise ValueError(
            f"Invalid character in S3 key component ({label}): {part!r}. "
            "NUL, '/', and '\\' are not allowed."
        )


class S3WorkspaceStore(WorkspaceStore):
    """aioboto3-backed workspace store for production S3 / MinIO."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix_root: str,
        region: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._prefix_root = prefix_root
        self._region = region
        self._endpoint_url = endpoint_url
        self._session = aioboto3.Session()

    def _object_key(self, key: WorkspaceKey, *parts: str) -> str:
        """Build an S3 object key. Validates all components; rejects traversal."""
        # WorkspaceKey fields are already validated by __post_init__.
        # Still check runtime parts for '/' and NUL.
        for part in (key.org_id, key.user_id, key.notebook_id):
            _check_part(part, "WorkspaceKey field")
        for part in parts:
            # Parts may contain '/' as path separators (e.g. "snapshots/ver/dir/file")
            # — we check individual segments.
            for segment in part.split("/"):
                if segment in _FORBIDDEN:
                    raise ValueError(f"Invalid S3 key segment: {segment!r}")
                if "\x00" in segment or "\\" in segment:
                    raise ValueError(f"Invalid character in S3 key segment: {segment!r}")
        tail = "/".join(parts)
        return f"{self._prefix_root}/org/{key.org_id}/user/{key.user_id}/notebook/{key.notebook_id}/{tail}"

    def _client_kwargs(self) -> dict:
        kwargs: dict = {"region_name": self._region}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return kwargs

    async def exists(self, key: WorkspaceKey) -> bool:
        manifest_key = self._object_key(key, _MANIFEST_KEY)
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=manifest_key)
                return True
            except ClientError as exc:
                # H3: only treat 404/NoSuchKey as "not found"; re-raise anything else
                # (auth expiry, bucket policy denial, network failure) so misconfig is visible.
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise

    async def hydrate(self, key: WorkspaceKey, dest: Path) -> HydrateResult:
        """Download latest snapshot into dest. cold_start=True if no manifest."""
        manifest_key = self._object_key(key, _MANIFEST_KEY)

        async with self._session.client("s3", **self._client_kwargs()) as s3:
            # Try to fetch manifest.
            try:
                resp = await s3.get_object(Bucket=self._bucket, Key=manifest_key)
                manifest_bytes = await resp["Body"].read()
            except Exception:
                logger.info("Cold start for notebook %s (no manifest)", key.notebook_id)
                return HydrateResult(
                    manifest_version=None,
                    file_count=0,
                    bytes_copied=0,
                    cold_start=True,
                )

            # Parse manifest. Malformed → cold start with warning.
            try:
                m = deserialize(manifest_bytes)
            except ValueError as exc:
                logger.warning(
                    "Malformed manifest for notebook %s: %s — treating as cold start",
                    key.notebook_id,
                    exc,
                )
                return HydrateResult(
                    manifest_version=None,
                    file_count=0,
                    bytes_copied=0,
                    cold_start=True,
                )

            # List all objects under snapshots/<version>/.
            prefix = self._object_key(key, f"snapshots/{m.version}/")
            objects: list[dict] = []
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                objects.extend(page.get("Contents", []))

            if not objects and m.file_count > 0:
                raise RuntimeError(
                    f"Manifest points to missing snapshot tree {m.version!r} "
                    f"for notebook {key.notebook_id}"
                )

            # Download all files.
            file_count = 0
            bytes_copied = 0
            for obj in objects:
                obj_key: str = obj["Key"]
                # Derive relative path from the prefix.
                rel = obj_key[len(prefix):]
                if not rel:
                    continue
                # H5: Reject path traversal in S3 keys — defense-in-depth against
                # external tooling that may write ../ segments outside _object_key.
                rel_path = Path(rel)
                if rel_path.is_absolute() or ".." in rel_path.parts:
                    raise RuntimeError(
                        f"S3 key contains path traversal: {obj_key!r}"
                    )
                dst_file = dest / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                resp = await s3.get_object(Bucket=self._bucket, Key=obj_key)
                data = await resp["Body"].read()
                dst_file.write_bytes(data)
                bytes_copied += len(data)
                file_count += 1

        return HydrateResult(
            manifest_version=m.version,
            file_count=file_count,
            bytes_copied=bytes_copied,
            cold_start=False,
        )

    async def _put_object(self, s3, *, key: str, data: bytes) -> None:
        """PUT a single object with SSE. Raises on non-2xx (aioboto3 raises on error)."""
        await s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ServerSideEncryption="AES256",
        )

    async def snapshot(self, key: WorkspaceKey, src: Path) -> SnapshotResult:
        """Upload src as a new snapshot. Manifest pointer written LAST (C2).

        asyncio.gather is called over ALL data-object PUTs. If ANY raises, we
        abort — the manifest pointer is NOT written. This guarantees that every
        observed manifest pointer references a complete snapshot tree.
        """
        version = uuid4().hex
        # V2: skip symlinks before is_file() to prevent symlink-following during snapshot.
        all_files = [f for f in src.rglob("*") if not f.is_symlink() and f.is_file()]
        skipped: list[str] = []
        upload_items: list[tuple[str, bytes]] = []  # (s3_key, data)

        for src_file in all_files:
            size = src_file.stat().st_size
            if size > MAX_FILE_BYTES:
                rel_str = str(src_file.relative_to(src))
                logger.warning(
                    "Skipping over-size file %s (%d bytes) for notebook %s",
                    rel_str,
                    size,
                    key.notebook_id,
                )
                skipped.append(rel_str)
                continue
            rel = str(src_file.relative_to(src))
            s3_key = self._object_key(key, f"snapshots/{version}/{rel}")
            data = src_file.read_bytes()
            upload_items.append((s3_key, data))

        async with self._session.client("s3", **self._client_kwargs()) as s3:
            # Step 1: Upload ALL data files concurrently.
            # If any PUT fails, asyncio.gather raises and we abort — no manifest write.
            put_tasks = [
                self._put_object(s3, key=s3_key, data=data)
                for s3_key, data in upload_items
            ]

            # C2: gather MUST complete before manifest pointer is written.
            # On any failure, this raises and we never reach the manifest PUT below.
            await asyncio.gather(*put_tasks)

            # Step 2: ONLY after all data PUTs succeed, write manifest pointer.
            # This assert documents the invariant: we only reach here on success.
            assert len(put_tasks) == len(upload_items), "put_tasks/upload_items mismatch"

            total_bytes = sum(len(data) for _, data in upload_items)
            m = Manifest(
                version=version,
                created_at_utc=datetime.now(timezone.utc).isoformat(),
                file_count=len(upload_items),
                bytes=total_bytes,
                skipped_paths=tuple(skipped),
            )
            manifest_key = self._object_key(key, _MANIFEST_KEY)
            await self._put_object(s3, key=manifest_key, data=serialize(m))

        logger.info(
            "S3 snapshot %s for notebook %s (%d files, %d bytes, %d skipped)",
            version,
            key.notebook_id,
            len(upload_items),
            total_bytes,
            len(skipped),
        )
        return SnapshotResult(
            manifest_version=version,
            file_count=len(upload_items),
            bytes_uploaded=total_bytes,
            skipped_paths=tuple(skipped),
        )
