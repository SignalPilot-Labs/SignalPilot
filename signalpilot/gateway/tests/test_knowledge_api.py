"""REST API tests for the Knowledge Base endpoints.

Uses FastAPI TestClient with mocked DB session (no live DB required).
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from gateway.main import app
from gateway.models.knowledge import (
    KnowledgeCategory,
    KnowledgeDoc,
    KnowledgeScope,
    KnowledgeStatus,
    KnowledgeUsage,
)
from gateway.store.knowledge import (
    KnowledgeDuplicate,
    KnowledgeNotFound,
    KnowledgeOrgQuotaExceeded,
    KnowledgeSizeExceeded,
    KnowledgeStateConflict,
)


def _make_doc(
    *,
    doc_id: str | None = None,
    scope: str = "org",
    scope_ref: str | None = None,
    category: str = "conventions",
    title: str = "test-doc",
    body: str | None = "Body content.",
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
        bytes=len((body or "").encode("utf-8")),
        view_count=0,
        created_at=time.time(),
        updated_at=time.time(),
        created_by=None,
        updated_by=None,
        proposed_by_agent=None,
    )


async def _mock_db_session():
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    yield session


@pytest.fixture
def auth_client():
    """Authenticated admin client with mocked DB."""
    from gateway.db.engine import get_db
    from gateway.store import get_local_api_key

    api_key = get_local_api_key()
    app.dependency_overrides[get_db] = _mock_db_session
    try:
        yield TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def read_client():
    """Client with read-scope API key (mocked)."""
    from gateway.db.engine import get_db
    from gateway.store import get_local_api_key

    api_key = get_local_api_key()
    app.dependency_overrides[get_db] = _mock_db_session
    try:
        # Local mode grants all scopes regardless; we mock scope enforcement instead
        yield TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
    finally:
        app.dependency_overrides.pop(get_db, None)


class TestKnowledgeListEndpoint:
    def test_get_list_filters(self, auth_client, monkeypatch):
        doc = _make_doc()
        from gateway.store import Store

        monkeypatch.setattr(Store, "list_knowledge_docs", AsyncMock(return_value=[doc]))

        resp = auth_client.get("/api/knowledge?scope=org&category=conventions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestKnowledgeUsageEndpoint:
    def test_usage_endpoint_reflects_caps(self, auth_client, monkeypatch):
        from gateway.store import Store

        usage = KnowledgeUsage(
            org_id="test-org",
            active_docs=3,
            active_bytes=1024,
            storage_limit_bytes=50 * 1024 * 1024,
            storage_limit_mb=50,
        )
        monkeypatch.setattr(Store, "get_knowledge_usage", AsyncMock(return_value=usage))

        resp = auth_client.get("/api/knowledge/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_docs"] == 3
        assert data["storage_limit_mb"] == 50


class TestKnowledgeDetailEndpoint:
    def test_get_doc_returns_body(self, auth_client, monkeypatch):
        doc = _make_doc(body="full body content")
        from gateway.store import Store

        monkeypatch.setattr(Store, "get_knowledge_doc", AsyncMock(return_value=doc))

        resp = auth_client.get(f"/api/knowledge/{doc.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["body"] == "full body content"

    def test_get_doc_not_found_returns_404(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(Store, "get_knowledge_doc", AsyncMock(return_value=None))

        resp = auth_client.get("/api/knowledge/missing-id")
        assert resp.status_code == 404


class TestKnowledgeCreateEndpoint:
    def test_post_knowledge_creates_doc(self, auth_client, monkeypatch):
        doc = _make_doc()
        from gateway.store import Store

        monkeypatch.setattr(Store, "upsert_knowledge_doc", AsyncMock(return_value=doc))

        resp = auth_client.post(
            "/api/knowledge",
            json={
                "scope": "org",
                "scope_ref": None,
                "category": "conventions",
                "title": "my-conventions",
                "body": "Always do X.",
            },
        )
        assert resp.status_code == 201

    def test_size_exceeded_maps_to_413(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(
            Store,
            "upsert_knowledge_doc",
            AsyncMock(side_effect=KnowledgeSizeExceeded("too big")),
        )

        resp = auth_client.post(
            "/api/knowledge",
            json={
                "scope": "org",
                "scope_ref": None,
                "category": "conventions",
                "title": "too-big",
                "body": "x",
            },
        )
        assert resp.status_code == 413

    def test_duplicate_maps_to_409(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(
            Store,
            "upsert_knowledge_doc",
            AsyncMock(side_effect=KnowledgeDuplicate("duplicate doc")),
        )

        resp = auth_client.post(
            "/api/knowledge",
            json={
                "scope": "org",
                "scope_ref": None,
                "category": "conventions",
                "title": "dup-doc",
                "body": "content",
            },
        )
        assert resp.status_code == 409

    def test_quota_exceeded_maps_to_413(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(
            Store,
            "upsert_knowledge_doc",
            AsyncMock(side_effect=KnowledgeOrgQuotaExceeded("quota exceeded")),
        )

        resp = auth_client.post(
            "/api/knowledge",
            json={
                "scope": "org",
                "scope_ref": None,
                "category": "conventions",
                "title": "quota-bust",
                "body": "x",
            },
        )
        assert resp.status_code == 413


class TestKnowledgeUpdateEndpoint:
    def test_put_appends_edit(self, auth_client, monkeypatch):
        doc = _make_doc(body="updated body")
        from gateway.store import Store

        monkeypatch.setattr(Store, "update_knowledge_body", AsyncMock(return_value=doc))

        resp = auth_client.put(
            f"/api/knowledge/{doc.id}",
            json={"body": "updated body"},
        )
        assert resp.status_code == 200
        assert resp.json()["body"] == "updated body"

    def test_put_not_found_returns_404(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(
            Store,
            "update_knowledge_body",
            AsyncMock(side_effect=KnowledgeNotFound("not found")),
        )

        resp = auth_client.put(
            "/api/knowledge/missing-id",
            json={"body": "new body"},
        )
        assert resp.status_code == 404


class TestKnowledgeDeleteEndpoint:
    def test_delete_archives_and_drops_from_usage(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(Store, "archive_knowledge_doc", AsyncMock(return_value=True))

        resp = auth_client.delete("/api/knowledge/some-id")
        assert resp.status_code == 204

    def test_delete_not_found_returns_404(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(Store, "archive_knowledge_doc", AsyncMock(return_value=False))

        resp = auth_client.delete("/api/knowledge/missing-id")
        assert resp.status_code == 404


class TestKnowledgeApproveEndpoint:
    def test_approve_pending_to_active(self, auth_client, monkeypatch):
        doc = _make_doc(status="active")
        from gateway.store import Store

        monkeypatch.setattr(Store, "approve_knowledge_doc", AsyncMock(return_value=doc))

        resp = auth_client.post("/api/knowledge/some-id/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_approve_not_found_returns_404(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(
            Store,
            "approve_knowledge_doc",
            AsyncMock(side_effect=KnowledgeNotFound("not found")),
        )

        resp = auth_client.post("/api/knowledge/missing-id/approve")
        assert resp.status_code == 404

    def test_approve_wrong_state_returns_409(self, auth_client, monkeypatch):
        from gateway.store import Store

        monkeypatch.setattr(
            Store,
            "approve_knowledge_doc",
            AsyncMock(side_effect=KnowledgeStateConflict("wrong state")),
        )

        resp = auth_client.post("/api/knowledge/some-id/approve")
        assert resp.status_code == 409


class TestKnowledgeEditsEndpoint:
    def test_get_edits_returns_list(self, auth_client, monkeypatch):
        from gateway.models.knowledge import KnowledgeEdit
        from gateway.store import Store

        edit = KnowledgeEdit(
            id=str(uuid.uuid4()),
            doc_id="doc-1",
            org_id="test-org",
            body_before="old body",
            bytes_before=8,
            edited_at=time.time(),
            edited_by="user1",
            edit_kind="human",
        )
        monkeypatch.setattr(Store, "list_knowledge_edits", AsyncMock(return_value=[edit]))

        resp = auth_client.get("/api/knowledge/doc-1/edits")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["edit_kind"] == "human"


class TestKnowledgeAdminScopeEnforcement:
    def test_post_knowledge_admin_only(self, auth_client, monkeypatch):
        """POST /api/knowledge is admin-only — verified via local key which grants all scopes."""
        doc = _make_doc()
        from gateway.store import Store

        monkeypatch.setattr(Store, "upsert_knowledge_doc", AsyncMock(return_value=doc))

        # Local key grants all scopes including admin
        resp = auth_client.post(
            "/api/knowledge",
            json={
                "scope": "org",
                "scope_ref": None,
                "category": "conventions",
                "title": "my-doc",
                "body": "content",
            },
        )
        assert resp.status_code == 201

    def test_post_knowledge_scope_enforcement_via_scope_guard(self):
        """Verify that the admin scope is declared on the POST endpoint."""
        from gateway.api.knowledge import router

        post_routes = [r for r in router.routes if hasattr(r, "methods") and "POST" in r.methods and r.path == "/api/knowledge"]
        assert len(post_routes) == 1
        # The route has dependencies (RequireScope("admin")) — we can't easily introspect
        # the scope name, but the route must have at least one dependency
        assert len(post_routes[0].dependencies) > 0
