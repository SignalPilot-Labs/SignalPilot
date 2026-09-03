"""Snapshot and sweep of the run scratch directory.

Pure filesystem logic. No HTTP. The uploader sends what a sweep returns.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from signalpilot import _loggers

LOGGER = _loggers.sp_logger()

DEFAULT_MAX_BYTES = 25 * 1024 * 1024
# Directories that hold generated tooling output, never user artifacts.
_IGNORED_TOP_LEVEL_DIRS = frozenset({"dbt-target", "dbt-logs", "dbt-profiles"})
_IGNORED_SEGMENTS = frozenset({"__pycache__"})


def max_file_bytes() -> int:
    """Read the sandbox-side size cap from the environment."""
    raw = os.getenv("SP_CHAT_FILE_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_BYTES
    return value if value > 0 else DEFAULT_MAX_BYTES


def is_captured_path(relative_path: str) -> bool:
    """Return True when a scratch-relative posix path is an artifact.

    The rules match the gateway route and the web panel filter, so no file
    the sandbox uploads is ever rejected for its name alone.
    """
    if not relative_path or relative_path.startswith("/"):
        return False
    parts = PurePosixPath(relative_path).parts
    if not parts:
        return False
    for segment in parts:
        if not segment or segment in {".", ".."}:
            return False
        if segment.startswith("."):
            return False
        if segment in _IGNORED_SEGMENTS:
            return False
    if parts[0] in _IGNORED_TOP_LEVEL_DIRS:
        return False
    name = parts[-1]
    if name.endswith(".log"):
        return False
    # Notebook sources belong to the archive, not the artifacts panel.
    # Top-level notebooks belong to the archive; the dbt stub database is tooling.
    return not (len(parts) == 1 and name.endswith((".py", ".duckdb")))


@dataclass(frozen=True)
class Fingerprint:
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class CapturedFile:
    """One new, changed, or deleted scratch file ready for upload."""

    path: str
    data: bytes
    content_hash: str
    deleted: bool = False

    @property
    def size(self) -> int:
        return len(self.data)


def _walk(scratch: Path) -> dict[str, Fingerprint]:
    """Stat every eligible file under the scratch directory."""
    found: dict[str, Fingerprint] = {}
    if not scratch.is_dir():
        return found
    pending = [scratch]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                relative = Path(entry.path).relative_to(scratch).as_posix()
                if not is_captured_path(relative):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            found[relative] = Fingerprint(
                size=int(info.st_size), mtime_ns=int(info.st_mtime_ns)
            )
    return found


class ScratchFileCapture:
    """Track scratch files by fingerprint and return what changed."""

    def __init__(
        self,
        *,
        scratch: Path,
        run_id: str,
        max_bytes: int | None = None,
        redactions: tuple[str, ...] = (),
    ) -> None:
        self.scratch = Path(scratch)
        self.run_id = run_id
        self.max_bytes = max_bytes if max_bytes else max_file_bytes()
        self._redactions = tuple(
            value.encode("utf-8") for value in redactions if value
        )
        self._snapshot: dict[str, Fingerprint] = {}

    @property
    def snapshot(self) -> dict[str, Fingerprint]:
        return dict(self._snapshot)

    def forget(self, relative_path: str) -> None:
        """Drop a path so the next sweep reads it again."""
        self._snapshot.pop(relative_path, None)

    async def baseline(self) -> None:
        """Snapshot every eligible file without reading its bytes."""
        self._snapshot = await asyncio.to_thread(_walk, self.scratch)

    async def sweep(
        self, *, reason: str, tool_call_id: str | None
    ) -> list[CapturedFile]:
        """Diff the scratch against the snapshot.

        Return new or changed files with bytes and sha256, and deleted
        files with no bytes. Update the snapshot for each returned file.
        """
        current = await asyncio.to_thread(_walk, self.scratch)
        captured: list[CapturedFile] = []
        for relative, fingerprint in current.items():
            if self._snapshot.get(relative) == fingerprint:
                continue
            file = await asyncio.to_thread(
                self._read, relative, fingerprint, reason, tool_call_id
            )
            if file is not None:
                captured.append(file)
        for relative in list(self._snapshot):
            if relative in current:
                continue
            del self._snapshot[relative]
            captured.append(
                CapturedFile(
                    path=relative,
                    data=b"",
                    content_hash=hashlib.sha256(b"").hexdigest(),
                    deleted=True,
                )
            )
        return captured

    def _read(
        self,
        relative: str,
        fingerprint: Fingerprint,
        reason: str,
        tool_call_id: str | None,
    ) -> CapturedFile | None:
        if fingerprint.size > self.max_bytes:
            LOGGER.warning(
                "Chat file skipped: over size cap run_id=%s path=%s "
                "size=%s cap=%s reason=%s",
                self.run_id,
                relative,
                fingerprint.size,
                self.max_bytes,
                reason,
            )
            # Remember the oversize fingerprint. A later change is re-read.
            self._snapshot[relative] = fingerprint
            return None
        try:
            data = (self.scratch / relative).read_bytes()
        except OSError:
            self._snapshot.pop(relative, None)
            return None
        if len(data) > self.max_bytes:
            self._snapshot[relative] = fingerprint
            return None
        if any(secret in data for secret in self._redactions):
            LOGGER.warning(
                "Chat file refused: content holds a runtime secret "
                "run_id=%s path=%s reason=%s tool_call_id=%s",
                self.run_id,
                relative,
                reason,
                tool_call_id or "",
            )
            # Drop the path so a later change is evaluated again.
            self._snapshot.pop(relative, None)
            return None
        self._snapshot[relative] = fingerprint
        return CapturedFile(
            path=relative,
            data=data,
            content_hash=hashlib.sha256(data).hexdigest(),
        )
