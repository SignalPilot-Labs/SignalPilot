"""Workspace snapshot manifest — serialization/deserialization.

Manifest format (S7):
    json.dumps(..., sort_keys=True, separators=(",", ":")).encode()

No tree_sha256 (S5 — unused, cut).
No _manifest.history/ (S11 — cut).

The manifest pointer (_manifest.current.json) is written LAST, AFTER all
data files have been successfully written. This is enforced by each backend.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class Manifest:
    """Snapshot manifest. version is a uuid4 hex string."""

    version: str
    created_at_utc: str  # ISO 8601, e.g. "2026-05-20T10:00:00Z"
    file_count: int
    bytes: int
    skipped_paths: tuple[str, ...]


def serialize(m: Manifest) -> bytes:
    """Serialize a Manifest to JSON bytes using compact, sort-keyed encoding (S7)."""
    data = {
        "version": m.version,
        "created_at_utc": m.created_at_utc,
        "file_count": m.file_count,
        "bytes": m.bytes,
        "skipped_paths": list(m.skipped_paths),
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def deserialize(b: bytes) -> Manifest:
    """Deserialize a Manifest from JSON bytes. Raises ValueError on malformed input."""
    try:
        data = json.loads(b)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed manifest JSON: {exc}") from exc
    try:
        version = data["version"]
        file_count = data["file_count"]
        total_bytes = data["bytes"]
        created_at_utc = data["created_at_utc"]
        skipped_paths = data.get("skipped_paths", [])
    except KeyError as exc:
        raise ValueError(f"Manifest missing required field: {exc}") from exc

    # H6: validate types so that a malformed manifest doesn't propagate through
    # to S3 key construction or arithmetic (e.g. version=["a","b"] would break keys).
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise ValueError(
            f"Manifest 'version' must be a 32-char hex string, got: {version!r}"
        )
    if not isinstance(file_count, int) or file_count < 0:
        raise ValueError(
            f"Manifest 'file_count' must be a non-negative int, got: {file_count!r}"
        )
    if not isinstance(total_bytes, int) or total_bytes < 0:
        raise ValueError(
            f"Manifest 'bytes' must be a non-negative int, got: {total_bytes!r}"
        )
    if not isinstance(skipped_paths, list):
        raise ValueError(
            f"Manifest 'skipped_paths' must be a list, got: {type(skipped_paths).__name__}"
        )

    return Manifest(
        version=version,
        created_at_utc=created_at_utc,
        file_count=file_count,
        bytes=total_bytes,
        skipped_paths=tuple(skipped_paths),
    )
