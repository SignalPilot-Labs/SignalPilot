"""Live mirror of agent file-tool writes into conversation storage.

This code runs inside the chat worker hot loop. It must never raise and
must never slow a run down on failure. Any problem is a silent skip; the
phase-2 sweep reconciles what the mirror misses.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import posixpath
import re
import time
import uuid
from typing import Any

from gateway.db.engine import get_session_factory
from gateway.standalone_chat.object_storage import (
    chat_object_storage,
    conversation_file_key,
)
from gateway.store import standalone_chat as chat_store

logger = logging.getLogger(__name__)

_MAX_WRITE_BYTES = 100 * 1024 * 1024
_MAX_EDIT_SOURCE_BYTES = 10 * 1024 * 1024
_EVENT_DEBOUNCE_SECONDS = 2.0
_TOOL_SUFFIXES = ("Write", "Edit", "MultiEdit")
_SKIPPED_BASENAMES = {".gateway-token", "analysis.py"}
_SKIPPED_SEGMENTS = {"__pycache__", ".git"}

# One files_changed event per run per debounce window.
_last_event_at: dict[str, float] = {}


def reset_debounce(run_id: str) -> None:
    """Clear the debounce clock for one run. Test hook."""
    _last_event_at.pop(run_id, None)


def _scratch_root() -> str:
    root = os.getenv("SP_CHAT_SCRATCH_ROOT", "/tmp/signalpilot-chat-runs").strip()
    return (root or "/tmp/signalpilot-chat-runs").rstrip("/")


def _relative_scratch_path(file_path: Any) -> str | None:
    """Validate one tool path and return it relative to the scratch root."""
    if not isinstance(file_path, str) or not file_path.startswith("/"):
        return None
    normalized = posixpath.normpath(file_path)
    root = _scratch_root()
    if not normalized.startswith(root + "/"):
        return None
    relative = normalized[len(root) + 1 :]
    if not relative:
        return None
    segments = relative.split("/")
    if any(segment in _SKIPPED_SEGMENTS for segment in segments):
        return None
    basename = segments[-1]
    if basename.startswith(".") or basename in _SKIPPED_BASENAMES:
        return None
    return relative


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f\"\\]")


def _display_filename(basename: str) -> str:
    """Strip characters that break headers or reads from a display name."""
    cleaned = _CONTROL_CHARS.sub("_", basename).strip()
    return cleaned[:255] or "file"


def execution_secrets(execution: Any) -> tuple[str, ...]:
    """Secret values the file mirror must refuse to store."""
    payload = getattr(execution, "payload", None)
    token = payload.get("gateway_session_token") if isinstance(payload, dict) else None
    return (token,) if isinstance(token, str) and token else ()


def _contains_secret(data: bytes, secrets: tuple[str, ...]) -> bool:
    """True when any known secret value appears in the bytes."""
    return any(secret and secret.encode("utf-8") in data for secret in secrets)


async def _sha256_hex(data: bytes) -> str:
    """Hash off the event loop. Uploads can reach 100 MB."""
    return await asyncio.to_thread(lambda: hashlib.sha256(data).hexdigest())


def _edit_list(tool_name: str, tool_input: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the sequential edit list for Edit or MultiEdit input."""
    if tool_name.endswith("MultiEdit"):
        edits = tool_input.get("edits")
        if not isinstance(edits, list) or not edits:
            return None
        if not all(isinstance(edit, dict) for edit in edits):
            return None
        return edits
    return [tool_input]


def _apply_edits(text: str, edits: list[dict[str, Any]]) -> str | None:
    """Apply edits in order. Return None when any edit does not match."""
    for edit in edits:
        old_string = edit.get("old_string")
        new_string = edit.get("new_string")
        if not isinstance(old_string, str) or not old_string:
            return None
        if not isinstance(new_string, str):
            return None
        if old_string not in text:
            return None
        count = -1 if edit.get("replace_all") else 1
        text = text.replace(old_string, new_string, count)
    return text


async def _emit_files_changed(run_id: str) -> None:
    """Append one debounced files_changed event for the run."""
    now = time.monotonic()
    last = _last_event_at.get(run_id)
    if last is not None and now - last < _EVENT_DEBOUNCE_SECONDS:
        return
    _last_event_at[run_id] = now
    if len(_last_event_at) > 1024:
        # Drop stale clocks so the map stays small.
        cutoff = now - _EVENT_DEBOUNCE_SECONDS
        for key in [key for key, ts in _last_event_at.items() if ts < cutoff]:
            _last_event_at.pop(key, None)
    # Import lazily. The worker module imports this module.
    from gateway.standalone_chat.worker import _append

    await _append(run_id, "files_changed", {"changed": 1})


async def _mirror(
    *,
    run_id: str,
    org_id: str,
    user_id: str,
    conversation_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    secrets: tuple[str, ...],
) -> None:
    storage = chat_object_storage()
    if not storage.enabled:
        return
    relative = _relative_scratch_path(tool_input.get("file_path"))
    if relative is None:
        return
    filename = _display_filename(posixpath.basename(relative))
    factory = get_session_factory()
    async with factory() as db:
        existing = await chat_store.get_conversation_file_by_path(
            db,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            path=relative,
        )
        if tool_name.endswith("Write"):
            content = tool_input.get("content")
            if not isinstance(content, str):
                return
            data = content.encode("utf-8")
            if len(data) > _MAX_WRITE_BYTES:
                return
            if existing is not None:
                object_key = existing.object_key
            else:
                file_id = str(uuid.uuid4())
                object_key = conversation_file_key(
                    org_id=org_id,
                    conversation_id=conversation_id,
                    file_id=file_id,
                    filename=filename,
                )
        else:
            # Edit and MultiEdit rewrite the stored object in place.
            if existing is None:
                return
            edits = _edit_list(tool_name, tool_input)
            if edits is None:
                return
            source = await storage.get_bytes(existing.object_key, max_bytes=_MAX_EDIT_SOURCE_BYTES)
            text = source.decode("utf-8")
            edited = _apply_edits(text, edits)
            if edited is None:
                # The stored copy diverged from the sandbox. Drop the row so
                # the panel never shows stale content as current. The
                # phase-2 sweep restores the true file.
                await chat_store.mark_conversation_file_deleted(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    path=relative,
                )
                await _emit_files_changed(run_id)
                return
            data = edited.encode("utf-8")
            object_key = existing.object_key
        if _contains_secret(data, secrets):
            # Same refusal the notebook archive applies to token-bearing
            # bytes. Never store run credentials durably.
            return
        mime_type = mimetypes.guess_type(filename)[0]
        await storage.put_bytes(
            key=object_key,
            data=data,
            content_type=mime_type or "application/octet-stream",
        )
        await chat_store.upsert_conversation_file(
            db,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            path=relative,
            filename=filename,
            mime_type=mime_type,
            byte_size=len(data),
            content_hash=await _sha256_hex(data),
            object_key=object_key,
            origin_run_id=run_id,
            origin="mirror",
        )
    await _emit_files_changed(run_id)


async def mirror_file_tool(
    *,
    run_id: str,
    org_id: str,
    user_id: str,
    conversation_id: str,
    tool_name: str,
    tool_input: Any,
    secrets: tuple[str, ...] = (),
) -> None:
    """Mirror one file-tool call into conversation storage. Never raises."""
    if not isinstance(tool_name, str) or not tool_name.endswith(_TOOL_SUFFIXES):
        return
    if not isinstance(tool_input, dict):
        return
    try:
        await _mirror(
            run_id=run_id,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            tool_input=tool_input,
            secrets=secrets,
        )
    except Exception:
        logger.debug(
            "chat file mirror skipped run=%s tool=%s",
            run_id,
            tool_name,
            exc_info=True,
        )
