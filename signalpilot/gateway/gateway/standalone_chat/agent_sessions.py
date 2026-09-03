"""Durable Claude Agent SDK session archives for standalone conversations."""

from __future__ import annotations

import re
from typing import Any

from gateway.standalone_chat.object_storage import (
    chat_object_storage,
    conversation_prefix,
)

_SAFE_ID = re.compile(r"^[a-zA-Z0-9-]{1,160}$")


def agent_session_archive_key(*, org_id: str, conversation_id: str) -> str:
    """Return an organization-isolated, deterministic archive key."""
    if not _SAFE_ID.fullmatch(conversation_id):
        raise ValueError("Invalid conversation id for agent session storage")
    return (
        f"{conversation_prefix(org_id, conversation_id)}"
        "/claude-agent/session.tgz"
    )


async def agent_session_transfer(
    *, org_id: str, conversation_id: str
) -> dict[str, Any]:
    """Create short-lived, object-scoped URLs for sandbox restore and save."""
    transfer: dict[str, Any] = {
        "session_id": conversation_id,
        "storage": "unavailable",
    }
    storage = chat_object_storage()
    if not storage.enabled:
        return transfer
    key = agent_session_archive_key(
        org_id=org_id,
        conversation_id=conversation_id,
    )
    transfer.update(
        {
            "storage": "s3",
            "download_url": await storage.presign_get(key, expires_seconds=3600),
            "upload_url": await storage.presign_put(key, expires_seconds=3600),
        }
    )
    return transfer
