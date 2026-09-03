"""Restore and persist native Claude Agent SDK conversation state."""

from __future__ import annotations

import asyncio
import io
import os
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

_SAFE_ID = re.compile(r"^[a-zA-Z0-9-]{1,160}$")
_MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_FILES = 20_000


@dataclass(frozen=True)
class ClaudeSessionState:
    session_id: str
    config_dir: Path
    cwd: Path
    resume: bool
    storage: str
    upload_url: str | None


def _bounded_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url or len(url) > 10_000:
        return None
    if urlsplit(url).scheme not in {"http", "https"}:
        return None
    return url


def _config_root() -> Path:
    return Path(
        os.getenv(
            "SP_CHAT_CLAUDE_STATE_ROOT",
            "/home/notebook/.sp/claude-sessions",
        )
    ).resolve()


def _config_dir(conversation_id: str) -> Path:
    if not _SAFE_ID.fullmatch(conversation_id):
        raise ValueError("Invalid conversation id for Claude session state")
    root = _config_root()
    target = (root / conversation_id).resolve()
    if root not in target.parents:
        raise ValueError("Claude session path escaped its configured root")
    return target


def _project_storage_name(cwd: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", str(cwd.resolve()))


def _has_session(config_dir: Path, session_id: str, cwd: Path) -> bool:
    return (
        config_dir
        / "projects"
        / _project_storage_name(cwd)
        / f"{session_id}.jsonl"
    ).is_file()


def _extract_archive(data: bytes, config_dir: Path) -> None:
    if len(data) > _MAX_COMPRESSED_BYTES:
        raise ValueError("Claude session archive exceeds the compressed size limit")
    config_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{config_dir.name}-restore-",
        dir=config_dir.parent,
    ) as temp_name:
        destination = Path(temp_name)
        total_size = 0
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > _MAX_ARCHIVE_FILES:
                raise ValueError("Claude session archive contains too many files")
            for member in members:
                if member.issym() or member.islnk() or member.isdev():
                    raise ValueError("Claude session archive contains an unsafe entry")
                member_path = (destination / member.name).resolve()
                if destination != member_path and destination not in member_path.parents:
                    raise ValueError("Claude session archive contains path traversal")
                total_size += max(0, member.size)
                if total_size > _MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Claude session archive exceeds the expanded size limit")
            archive.extractall(destination, members=members, filter="data")
        if config_dir.exists():
            shutil.rmtree(config_dir)
        shutil.move(str(destination), str(config_dir))


def _create_archive(config_dir: Path) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path in sorted(config_dir.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink() or not path.is_file():
                continue
            archive.add(path, arcname=path.relative_to(config_dir).as_posix(), recursive=False)
    data = output.getvalue()
    if len(data) > _MAX_COMPRESSED_BYTES:
        raise ValueError("Claude session archive exceeds the compressed size limit")
    return data


async def prepare_claude_session(
    *, conversation_id: str, cwd: Path, transfer: dict[str, Any] | None
) -> ClaudeSessionState:
    """Use local native state immediately, otherwise restore it from S3."""
    transfer = transfer if isinstance(transfer, dict) else {}
    session_id = str(transfer.get("session_id") or conversation_id)
    if session_id != conversation_id or not _SAFE_ID.fullmatch(session_id):
        raise ValueError("Claude session id does not match the conversation")
    config_dir = _config_dir(conversation_id)
    upload_url = _bounded_url(transfer.get("upload_url"))
    storage = str(transfer.get("storage") or "unavailable")
    if _has_session(config_dir, session_id, cwd):
        return ClaudeSessionState(
            session_id=session_id,
            config_dir=config_dir,
            cwd=cwd,
            resume=True,
            storage=storage,
            upload_url=upload_url,
        )

    download_url = _bounded_url(transfer.get("download_url"))
    if download_url:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.get(download_url)
        if response.status_code == 200:
            await asyncio.to_thread(_extract_archive, response.content, config_dir)
        elif response.status_code not in {403, 404}:
            response.raise_for_status()

    config_dir.mkdir(parents=True, exist_ok=True)
    return ClaudeSessionState(
        session_id=session_id,
        config_dir=config_dir,
        cwd=cwd,
        resume=_has_session(config_dir, session_id, cwd),
        storage=storage,
        upload_url=upload_url,
    )


async def persist_claude_session(state: ClaudeSessionState) -> bool:
    """Upload the complete native SDK state after a turn."""
    if not state.upload_url or not _has_session(
        state.config_dir, state.session_id, state.cwd
    ):
        return False
    data = await asyncio.to_thread(_create_archive, state.config_dir)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
        response = await client.put(
            state.upload_url,
            content=data,
            headers={"Content-Type": "application/gzip"},
        )
    response.raise_for_status()
    return True
