"""Local filesystem workspace store — dev/test backend.

Layout mirrors the S3 layout under a local root directory:
    <root>/org/<org_id>/user/<user_id>/notebook/<notebook_id>/
        snapshots/<version>/<relpath>
        _manifest.current.json

Atomic pointer commit: data files written first, then os.replace of a .tmp file
over the manifest pointer — matches POSIX atomicity guarantees.

All paths are validated: '..' and NUL bytes are rejected. Only [a-zA-Z0-9_-] is
allowed in WorkspaceKey fields (enforced by WorkspaceKey.__post_init__).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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

_MANIFEST_FILENAME = "_manifest.current.json"
_MANIFEST_TMP_SUFFIX = ".tmp"

_FORBIDDEN_PATH_PARTS = {"..", ""}


def _check_path_part(part: str) -> None:
    """Reject path traversal attempts: '..', empty string, NUL bytes."""
    if part in _FORBIDDEN_PATH_PARTS or "\x00" in part:
        raise ValueError(f"Invalid path component: {part!r}")


def _workspace_root(root: Path, key: WorkspaceKey) -> Path:
    """Return the directory for a given workspace key, rejecting path traversal."""
    for part in (key.org_id, key.user_id, key.notebook_id):
        _check_path_part(part)
    return root / "org" / key.org_id / "user" / key.user_id / "notebook" / key.notebook_id


def _manifest_path(ws_root: Path) -> Path:
    return ws_root / _MANIFEST_FILENAME


class LocalWorkspaceStore(WorkspaceStore):
    """Filesystem-backed workspace store. Suitable for local dev and tests."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def exists(self, key: WorkspaceKey) -> bool:
        ws_root = _workspace_root(self._root, key)
        return _manifest_path(ws_root).exists()

    async def hydrate(self, key: WorkspaceKey, dest: Path) -> HydrateResult:
        """Download latest snapshot into dest. cold_start=True if no manifest."""
        ws_root = _workspace_root(self._root, key)
        manifest_file = _manifest_path(ws_root)

        if not manifest_file.exists():
            logger.info("Cold start for notebook %s (no manifest)", key.notebook_id)
            return HydrateResult(
                manifest_version=None,
                file_count=0,
                bytes_copied=0,
                cold_start=True,
            )

        # Read and parse manifest. Malformed manifest → cold start with warning.
        try:
            m = deserialize(manifest_file.read_bytes())
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

        snapshot_dir = ws_root / "snapshots" / m.version
        if not snapshot_dir.exists():
            raise RuntimeError(
                f"Manifest points to missing snapshot tree {m.version!r} "
                f"for notebook {key.notebook_id}"
            )

        # Copy all files from snapshot_dir into dest.
        # V2: skip symlinks before is_file() check (is_file() follows symlinks by default).
        files = list(snapshot_dir.rglob("*"))
        file_count = 0
        bytes_copied = 0
        for src_file in files:
            if src_file.is_symlink():
                logger.warning("Skipping symlink in workspace hydrate: %s", src_file)
                continue
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(snapshot_dir)
            dst_file = dest / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            data = src_file.read_bytes()
            dst_file.write_bytes(data)
            bytes_copied += len(data)
            file_count += 1

        return HydrateResult(
            manifest_version=m.version,
            file_count=file_count,
            bytes_copied=bytes_copied,
            cold_start=False,
        )

    async def snapshot(self, key: WorkspaceKey, src: Path) -> SnapshotResult:
        """Write src directory contents as a new snapshot version.

        Data files are written BEFORE the manifest pointer is updated (C2).
        Uses os.replace for atomic manifest pointer commit.
        """
        ws_root = _workspace_root(self._root, key)
        version = uuid4().hex
        snapshot_dir = ws_root / "snapshots" / version

        # V2: skip symlinks before is_file() to prevent symlink-following during snapshot.
        all_files = [f for f in src.rglob("*") if not f.is_symlink() and f.is_file()]
        skipped: list[str] = []
        uploaded_files: list[tuple[Path, Path]] = []  # (src_file, dst_file)

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
            rel = src_file.relative_to(src)
            dst_file = snapshot_dir / rel
            uploaded_files.append((src_file, dst_file))

        # Write all data files BEFORE updating the manifest pointer (C2).
        total_bytes = 0
        for src_file, dst_file in uploaded_files:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            data = src_file.read_bytes()
            dst_file.write_bytes(data)
            total_bytes += len(data)

        # Build manifest AFTER all data files are written.
        m = Manifest(
            version=version,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            file_count=len(uploaded_files),
            bytes=total_bytes,
            skipped_paths=tuple(skipped),
        )
        manifest_bytes = serialize(m)

        # Atomic pointer update: write .tmp then os.replace (POSIX atomic).
        manifest_file = _manifest_path(ws_root)
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = Path(str(manifest_file) + _MANIFEST_TMP_SUFFIX)
        tmp_file.write_bytes(manifest_bytes)
        os.replace(tmp_file, manifest_file)  # atomic on POSIX

        logger.info(
            "Snapshot %s written for notebook %s (%d files, %d bytes, %d skipped)",
            version,
            key.notebook_id,
            len(uploaded_files),
            total_bytes,
            len(skipped),
        )
        return SnapshotResult(
            manifest_version=version,
            file_count=len(uploaded_files),
            bytes_uploaded=total_bytes,
            skipped_paths=tuple(skipped),
        )
