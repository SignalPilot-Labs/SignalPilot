"""MCP tool tests for the Knowledge Base module.

All tests mock the store and context variables — no live DB or MCP server required.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.models.knowledge import (
    KnowledgeCategory,
    KnowledgeDoc,
    KnowledgeScope,
    KnowledgeStatus,
)
from gateway.store.knowledge import KnowledgeDuplicate


def _make_doc(
    *,
    doc_id: str | None = None,
    scope: str = "org",
    scope_ref: str | None = None,
    category: str = "understanding",
    title: str = "test-doc",
    body: str = "Body content.",
    status: str = "active",
) -> KnowledgeDoc:
    return KnowledgeDoc(
        id=doc_id or str(uuid.uuid4()),
        org_id="test-org",
        scope=KnowledgeScope(scope),
        scope_ref=scope_ref,
        category=KnowledgeCategory(category),
        title=title,
        body=body,
        status=KnowledgeStatus(status),
        bytes=len(body.encode("utf-8")),
        view_count=0,
        created_at=time.time(),
        updated_at=time.time(),
        created_by=None,
        updated_by=None,
        proposed_by_agent=None,
    )


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.increment_knowledge_view = AsyncMock()
    store.list_knowledge_docs = AsyncMock(return_value=[])
    store.search_knowledge = AsyncMock(return_value=[])
    store.insert_knowledge_doc = AsyncMock()
    store.get_knowledge_doc = AsyncMock(return_value=None)
    store.archive_knowledge_doc = AsyncMock(return_value=True)
    return store


class TestGetKnowledgeTool:
    @pytest.mark.asyncio
    async def test_get_knowledge_returns_org_and_project_baseline(self, mock_store):
        org_doc = _make_doc(scope="org", category="understanding", title="org-understanding")
        proj_doc = _make_doc(scope="project", scope_ref="my-proj", category="understanding", title="proj-understanding")
        mock_store.list_knowledge_docs = AsyncMock(side_effect=[
            [org_doc],   # First call: org-scope docs
            [proj_doc],  # Second call: project-scope docs
        ])

        from gateway.mcp.tools.knowledge import get_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await get_knowledge.__wrapped__(task_description=None)

        assert "org-understanding" in result
        assert "proj-understanding" in result

    @pytest.mark.asyncio
    async def test_get_knowledge_empty_returns_no_content_message(self, mock_store):
        mock_store.list_knowledge_docs = AsyncMock(return_value=[])

        from gateway.mcp.tools.knowledge import get_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await get_knowledge.__wrapped__(task_description=None)

        assert "No knowledge base content found" in result

    @pytest.mark.asyncio
    async def test_get_knowledge_caps_at_50_projects(self, mock_store):
        # Create 60 project docs across 60 distinct projects
        proj_docs = [
            _make_doc(
                scope="project",
                scope_ref=f"proj-{i:03d}",
                category="understanding",
                title=f"proj-doc-{i:03d}",
            )
            for i in range(60)
        ]
        mock_store.list_knowledge_docs = AsyncMock(side_effect=[
            [],         # org docs
            proj_docs,  # project docs
        ])

        from gateway.mcp.tools.knowledge import get_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await get_knowledge.__wrapped__(task_description=None)

        # At most 50 unique project refs should appear (each as scope_ref in output)
        unique_refs = {f"proj-{i:03d}" for i in range(60)}
        found_refs = sum(1 for ref in unique_refs if ref in result)
        assert found_refs <= 50

    @pytest.mark.asyncio
    async def test_get_knowledge_with_task_description_caps_keywords_at_12(self, mock_store):
        mock_store.list_knowledge_docs = AsyncMock(return_value=[])
        # A task description with many unique words
        task = " ".join(f"keyword{i}" for i in range(20))

        keyword_calls: list[str] = []

        async def capturing_search(*, query, **kwargs):
            keyword_calls.append(query)
            return []

        mock_store.search_knowledge = capturing_search

        from gateway.mcp.tools.knowledge import get_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await get_knowledge.__wrapped__(task_description=task)

        # Should have searched at most 12 distinct keywords
        assert len(keyword_calls) <= 12


class TestSearchKnowledgeTool:
    @pytest.mark.asyncio
    async def test_search_knowledge_pure_read_allows_understanding(self, mock_store):
        understanding_doc = _make_doc(category="understanding", title="org-understanding")
        mock_store.search_knowledge = AsyncMock(return_value=[understanding_doc])

        from gateway.mcp.tools.knowledge import search_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await search_knowledge.__wrapped__(query="something")

        assert "org-understanding" in result
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_search_knowledge_empty_query_rejected(self, mock_store):
        from gateway.mcp.tools.knowledge import search_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await search_knowledge.__wrapped__(query="   ")

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_search_knowledge_no_results_returns_not_found(self, mock_store):
        mock_store.search_knowledge = AsyncMock(return_value=[])

        from gateway.mcp.tools.knowledge import search_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await search_knowledge.__wrapped__(query="noresults")

        assert "No knowledge docs found" in result


class TestProposeKnowledgeTool:
    @pytest.mark.asyncio
    async def test_propose_knowledge_rejects_understanding(self, mock_store):
        from gateway.mcp.tools.knowledge import propose_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await propose_knowledge.__wrapped__(
                scope="org",
                scope_ref=None,
                category="understanding",
                title="my-doc",
                body="content",
            )

        assert "Refused" in result
        assert "human-authored" in result

    @pytest.mark.asyncio
    async def test_propose_knowledge_auto_accepts_decisions(self, mock_store):
        doc = _make_doc(scope="project", scope_ref="my-proj", category="decisions", status="active")
        mock_store.insert_knowledge_doc = AsyncMock(return_value=doc)

        from gateway.mcp.tools.knowledge import propose_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await propose_knowledge.__wrapped__(
                scope="project",
                scope_ref="my-proj",
                category="decisions",
                title="my-decision",
                body="We decided to do X.",
            )

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["doc_status"] == "active"

    @pytest.mark.asyncio
    async def test_propose_knowledge_pending_for_conventions(self, mock_store):
        doc = _make_doc(scope="org", category="conventions", status="pending")
        mock_store.insert_knowledge_doc = AsyncMock(return_value=doc)

        from gateway.mcp.tools.knowledge import propose_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await propose_knowledge.__wrapped__(
                scope="org",
                scope_ref=None,
                category="conventions",
                title="my-convention",
                body="Always use snake_case.",
            )

        data = json.loads(result)
        assert data["status"] == "created"
        assert data["doc_status"] == "pending"

    @pytest.mark.asyncio
    async def test_propose_knowledge_rejects_duplicate_returns_status_rejected_duplicate(self, mock_store):
        existing_id = str(uuid.uuid4())
        mock_store.insert_knowledge_doc = AsyncMock(
            side_effect=KnowledgeDuplicate("already exists", existing_id=existing_id)
        )

        from gateway.mcp.tools.knowledge import propose_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await propose_knowledge.__wrapped__(
                scope="org",
                scope_ref=None,
                category="conventions",
                title="my-convention",
                body="Already exists.",
            )

        data = json.loads(result)
        assert data["status"] == "rejected_duplicate"
        assert data["existing_id"] == existing_id

    @pytest.mark.asyncio
    async def test_propose_knowledge_supersedes_archives_then_inserts(self, mock_store):
        old_id = str(uuid.uuid4())
        old_doc = _make_doc(
            doc_id=old_id,
            scope="project",
            scope_ref="my-proj",
            category="decisions",
            title="my-decision",
        )
        new_doc = _make_doc(
            scope="project",
            scope_ref="my-proj",
            category="decisions",
            title="my-decision",
            status="active",
        )
        mock_store.get_knowledge_doc = AsyncMock(return_value=old_doc)
        mock_store.archive_knowledge_doc = AsyncMock(return_value=True)
        mock_store.insert_knowledge_doc = AsyncMock(return_value=new_doc)

        from gateway.mcp.tools.knowledge import propose_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await propose_knowledge.__wrapped__(
                scope="project",
                scope_ref="my-proj",
                category="decisions",
                title="my-decision",
                body="Updated decision.",
                supersedes=old_id,
            )

        mock_store.archive_knowledge_doc.assert_awaited_once_with(old_id)
        data = json.loads(result)
        assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_propose_knowledge_invalid_scope_returns_error(self, mock_store):
        from gateway.mcp.tools.knowledge import propose_knowledge

        with patch("gateway.mcp.tools.knowledge._store_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_store)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await propose_knowledge.__wrapped__(
                scope="not-a-scope",
                scope_ref=None,
                category="decisions",
                title="my-doc",
                body="content",
            )

        assert "Error" in result
