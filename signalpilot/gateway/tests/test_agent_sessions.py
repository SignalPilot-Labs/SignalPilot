from __future__ import annotations

from dataclasses import dataclass

import pytest

from gateway.standalone_chat import agent_sessions

CONVERSATION_ID = "11111111-2222-4333-8444-555555555555"


def test_archive_key_is_conversation_scoped_and_hides_org_id() -> None:
    key = agent_sessions.agent_session_archive_key(
        org_id="sensitive-org-name",
        conversation_id=CONVERSATION_ID,
    )

    assert "sensitive-org-name" not in key
    assert key.endswith(
        f"/conversations/{CONVERSATION_ID}/claude-agent/session.tgz"
    )


@pytest.mark.asyncio
async def test_transfer_returns_object_scoped_restore_and_save_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass
    class Storage:
        enabled: bool = True

        async def presign_get(self, key: str, *, expires_seconds: int) -> str:
            assert key.endswith("/claude-agent/session.tgz")
            assert expires_seconds == 3600
            return "https://storage.test/download"

        async def presign_put(self, key: str, *, expires_seconds: int) -> str:
            assert key.endswith("/claude-agent/session.tgz")
            assert expires_seconds == 3600
            return "https://storage.test/upload"

    monkeypatch.setattr(agent_sessions, "chat_object_storage", Storage)

    transfer = await agent_sessions.agent_session_transfer(
        org_id="org-a",
        conversation_id=CONVERSATION_ID,
    )

    assert transfer == {
        "session_id": CONVERSATION_ID,
        "storage": "s3",
        "download_url": "https://storage.test/download",
        "upload_url": "https://storage.test/upload",
    }
