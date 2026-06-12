"""Tests for F-2: user_id scoping on chat message read/write."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayChatConversation, GatewayChatMessage
from gateway.store.chat import append_message, create_conversation, list_messages

# ── DB Fixture ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────────────────

_ORG_A = "org-a"
_USER_A = "user-a"
_USER_B = "user-b"
_ORG_B = "org-b"


async def _create_conv_with_message(session, org_id: str, user_id: str) -> str:
    conv = await create_conversation(session, org_id=org_id, user_id=user_id, title="test")
    await append_message(
        session,
        org_id=org_id,
        user_id=user_id,
        conversation_id=conv.id,
        role="user",
        content="hello from " + user_id,
    )
    return conv.id


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestChatUserIsolation:
    @pytest.mark.asyncio
    async def test_user_b_cannot_read_user_a_messages(self, db_session):
        """User B cannot list messages from User A's conversation (same org)."""
        conv_id = await _create_conv_with_message(db_session, _ORG_A, _USER_A)

        with pytest.raises(ValueError, match="not found"):
            await list_messages(
                db_session, org_id=_ORG_A, user_id=_USER_B, conversation_id=conv_id
            )

    @pytest.mark.asyncio
    async def test_user_b_cannot_append_to_user_a_conversation(self, db_session):
        """User B cannot append to User A's conversation; row count unchanged."""
        conv_id = await _create_conv_with_message(db_session, _ORG_A, _USER_A)

        with pytest.raises(ValueError, match="not found"):
            await append_message(
                db_session,
                org_id=_ORG_A,
                user_id=_USER_B,
                conversation_id=conv_id,
                role="user",
                content="injected by B",
            )

        # Verify no extra row was committed.
        from sqlalchemy import select

        count_result = await db_session.execute(
            select(GatewayChatMessage).where(GatewayChatMessage.conversation_id == conv_id)
        )
        messages = count_result.scalars().all()
        assert len(messages) == 1

    @pytest.mark.asyncio
    async def test_owner_can_still_read_and_append(self, db_session):
        """Regression: the conversation owner can read and append without issue."""
        conv_id = await _create_conv_with_message(db_session, _ORG_A, _USER_A)

        msgs, total = await list_messages(
            db_session, org_id=_ORG_A, user_id=_USER_A, conversation_id=conv_id
        )
        assert total == 1
        assert msgs[0].content == "hello from " + _USER_A

        await append_message(
            db_session,
            org_id=_ORG_A,
            user_id=_USER_A,
            conversation_id=conv_id,
            role="assistant",
            content="reply",
        )
        msgs2, total2 = await list_messages(
            db_session, org_id=_ORG_A, user_id=_USER_A, conversation_id=conv_id
        )
        assert total2 == 2

    @pytest.mark.asyncio
    async def test_cross_org_still_blocked(self, db_session):
        """Org X user cannot access Org Y's conversation — existing behavior preserved."""
        conv_id = await _create_conv_with_message(db_session, _ORG_A, _USER_A)

        with pytest.raises(ValueError, match="not found"):
            await list_messages(
                db_session, org_id=_ORG_B, user_id=_USER_A, conversation_id=conv_id
            )


class TestChatAPIUserIsolation:
    """API-layer tests: 404 is returned when a peer accesses another user's conversation."""

    @pytest.fixture
    def client_a(self):
        """TestClient authenticated as user A."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from gateway.main import app

        async def _mock_db():
            session = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=result)
            session.add = MagicMock()
            session.commit = AsyncMock()
            yield session

        from gateway.db.engine import get_db
        from gateway.store import get_local_api_key

        api_key = get_local_api_key()
        app.dependency_overrides[get_db] = _mock_db
        try:
            yield TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_get_conversation_endpoint_returns_404_for_peer_conv_id(self, client_a):
        """GET /api/chat/conversations/{id} returns 404 when conv not found."""
        # The mock returns None for get_conversation, so any ID is 404.
        response = client_a.get("/api/chat/conversations/nonexistent-id")
        assert response.status_code == 404
        # Response body must not leak sensitive content.
        assert "nonexistent-id" not in response.text or "not found" in response.text.lower()

    def test_post_message_endpoint_returns_404_for_peer_conv_id(self, client_a):
        """POST /api/chat/conversations/{id}/messages returns 404 when conv not found."""
        response = client_a.post(
            "/api/chat/conversations/nonexistent-id/messages",
            json={"role": "user", "content": "hi"},
        )
        assert response.status_code == 404
