"""Store-layer tests for agent-proposed Knowledge Base docs (cloud-mode gating).

Continues ``test_knowledge_store.py``. All tests use mocked SQLAlchemy
sessions. no live DB required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.models.knowledge import KnowledgeCategory, KnowledgeDocCreate, KnowledgeScope
from gateway.store.knowledge import insert_knowledge_doc, upsert_knowledge_doc

from ._knowledge_store_helpers import _make_doc_row, _make_insert_session, _make_limits, _make_settings


class TestAgentProposalCloudGating:
    """Cloud-mode gating for agent-proposed knowledge docs."""

    @pytest.mark.asyncio
    async def test_agent_proposal_active_in_localhost(self, monkeypatch):
        """In localhost mode, agent-proposed docs are auto-accepted (status=active)."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        session, row = _make_insert_session()
        captured_rows: list = []

        def capture_add(r):
            captured_rows.append(r)

        session.add = MagicMock(side_effect=capture_add)

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.rules,
            title="test-doc",
            body="content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await insert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert len(captured_rows) == 1
        assert captured_rows[0].status == "active"

    @pytest.mark.asyncio
    async def test_agent_proposal_pending_in_cloud(self, monkeypatch):
        """In cloud mode, agent-proposed docs are forced to pending regardless of category."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        session, row = _make_insert_session()
        captured_rows: list = []

        def capture_add(r):
            captured_rows.append(r)

        session.add = MagicMock(side_effect=capture_add)

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.rules,
            title="test-doc",
            body="content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await insert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert len(captured_rows) == 1
        assert captured_rows[0].status == "pending"

    @pytest.mark.asyncio
    async def test_agent_upsert_update_pending_in_cloud(self, monkeypatch):
        """In cloud mode, agent update of an active doc forces status=pending."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        session = AsyncMock()
        existing = _make_doc_row(status="active", body="old content")

        call_count = 0

        async def execute_side_effect(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # _find_doc_by_key: returns existing row
                result.scalar_one_or_none.return_value = existing
            elif call_count == 2:
                # current_bytes query
                result.scalar.return_value = 100
            else:
                result.scalar_one_or_none.return_value = existing
                result.scalar_one.return_value = existing
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.rules,
            title=existing.title,
            body="new content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await upsert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert existing.status == "pending"

    @pytest.mark.asyncio
    async def test_human_upsert_update_keeps_active_in_cloud(self, monkeypatch):
        """In cloud mode, human update of an active doc does NOT change status."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")

        session = AsyncMock()
        existing = _make_doc_row(status="active", body="old content")

        call_count = 0

        async def execute_side_effect(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = existing
            elif call_count == 2:
                result.scalar.return_value = 100
            else:
                result.scalar_one_or_none.return_value = existing
                result.scalar_one.return_value = existing
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.rules,
            title=existing.title,
            body="new content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await upsert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id="admin-user",
            agent=None,
            limits=limits,
            settings=settings,
        )
        assert existing.status == "active"

    @pytest.mark.asyncio
    async def test_upsert_update_leaves_archived_doc_archived(self, monkeypatch):
        """An overwrite must not resurrect a tombstoned doc.

        Archived is a tombstone: reviving it on upsert let a guessed
        (scope, scope_ref, category, title) key silently bring back deleted
        knowledge via overwrite=True. Unarchiving is now explicit only.
        """
        """Editing an archived doc (local mode) revives it to active, not hidden."""
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        session = AsyncMock()
        existing = _make_doc_row(status="archived", body="old content")

        call_count = 0

        async def execute_side_effect(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = existing
            elif call_count == 2:
                result.scalar.return_value = 100
            else:
                result.scalar_one_or_none.return_value = existing
                result.scalar_one.return_value = existing
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org,
            scope_ref=None,
            category=KnowledgeCategory.rules,
            title=existing.title,
            body="new content",
        )
        limits = _make_limits()
        settings = _make_settings()

        await upsert_knowledge_doc(
            session,
            org_id="test-org",
            payload=payload,
            user_id=None,
            agent="propose_knowledge",
            limits=limits,
            settings=settings,
        )
        assert existing.status == "archived"
        assert existing.body == "new content"
