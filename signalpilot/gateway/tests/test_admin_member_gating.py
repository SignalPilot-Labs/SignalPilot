"""Admin/member gating: the member paths the brief opened, and the ownership rules it added.

Driven through the real app (local mode, local API key) with the org role
overridden per test, so the dependency wiring is exercised, not just the helpers.
Guard presence on every admin-only route is asserted by test_route_role_manifest.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gateway.api import keys as keys_api
from gateway.api.chat_report_access import report_actor, version_actor
from gateway.api.deps import get_store
from gateway.api.workspace_files import _require_branch_write
from gateway.auth import ADMIN_PERMISSIONS, MEMBER_PERMISSIONS
from gateway.auth.permissions import ADMIN_ROLE_REQUIRED, OWNERSHIP_DENIAL
from gateway.auth.user import resolve_org_role
from gateway.main import app
from gateway.models import ApiKeyRecord

ME = "user_me"
OTHER = "user_other"


def _key(key_id: str, user_id: str, scopes: list[str]) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=key_id,
        name=key_id,
        prefix="sp_" + key_id[:8],
        key_hash="0" * 64,
        scopes=scopes,
        created_at="2026-09-15T00:00:00+00:00",
        user_id=user_id,
        org_id="test-org",
    )


def _store(user_id: str = ME) -> MagicMock:
    store = MagicMock()
    store.org_id = "test-org"
    store.user_id = user_id
    store._require_org_id.return_value = "test-org"
    store.list_api_keys = AsyncMock(return_value=[])
    store.get_api_key = AsyncMock(return_value=None)
    store.delete_api_key = AsyncMock(return_value=True)
    store.create_api_key = AsyncMock(return_value=(_key("new", user_id, ["read"]), "sp_raw"))
    store.append_audit = AsyncMock()
    store.upsert_knowledge_doc = AsyncMock()
    store.insert_knowledge_doc = AsyncMock()
    store.list_connections = AsyncMock(return_value=[])
    return store


@pytest.fixture
def role():
    """Set the org role the app resolves for the request; default member."""
    state = {"role": "basic_member"}

    async def _role() -> str:
        return state["role"]

    app.dependency_overrides[resolve_org_role] = _role
    try:
        yield state
    finally:
        app.dependency_overrides.pop(resolve_org_role, None)


@pytest.fixture
def store():
    s = _store()
    app.dependency_overrides[get_store] = lambda: s
    try:
        yield s
    finally:
        app.dependency_overrides.pop(get_store, None)


@pytest.fixture
def client():
    from gateway.store import get_local_api_key

    return TestClient(app, headers={"Authorization": f"Bearer {get_local_api_key()}"})


@pytest.fixture(autouse=True)
def _no_key_limits(monkeypatch):
    monkeypatch.setattr("gateway.governance.org_limits.get_org_limits", AsyncMock(return_value=None))
    monkeypatch.setattr("gateway.governance.org_limits.check_api_key_limit", lambda *_: None)


# Every newly gated route refuses a member with OrgAdmin's detail, through the app.

GATED_ROUTES = [
    ("PUT", "/api/org/secrets"),
    ("POST", "/api/connections/test-credentials"),
    ("GET", "/api/audit"),
    ("GET", "/api/audit/stats"),
    ("GET", "/api/github/install-url"),
    ("DELETE", "/api/github/installations/x"),
    ("POST", "/api/github/repo-links"),
    ("DELETE", "/api/github/repo-links/x"),
    ("POST", "/api/github/sync/x"),
    ("POST", "/api/github/import"),
    ("POST", "/api/workspace-projects"),
    ("PUT", "/api/workspace-projects/x"),
    ("DELETE", "/api/workspace-projects/x"),
    ("POST", "/api/projects"),
    ("PUT", "/api/projects/x"),
    ("DELETE", "/api/projects/x"),
    ("POST", "/api/projects/x/scan"),
    ("PUT", "/api/connections/c/schema/endorsements"),
    ("POST", "/api/connections/c/schema/refine"),
    ("POST", "/api/connections/c/schema/correct-columns"),
    ("PUT", "/api/connections/c/semantic-model"),
    ("POST", "/api/connections/c/semantic-model/generate"),
    ("PUT", "/api/connections/c/pii"),
    ("POST", "/api/connections/c/detect-and-save-pii"),
    ("PUT", "/api/chat/default-project"),
    ("POST", "/api/budget"),
    ("DELETE", "/api/budget/x"),
    ("POST", "/api/evals/upload/initiate"),
    ("POST", "/api/evals/upload/complete"),
    ("POST", "/api/evals/upload/abort"),
]


@pytest.mark.parametrize("method,path", GATED_ROUTES, ids=[f"{m} {p}" for m, p in GATED_ROUTES])
def test_member_is_refused_on_every_newly_gated_route(client, role, store, method, path):
    body = {} if method in {"POST", "PUT"} else None
    r = client.request(method, path, json=body)
    assert r.status_code == 403, f"{method} {path}: {r.status_code} {r.text[:200]}"
    assert r.json()["detail"] == ADMIN_ROLE_REQUIRED


# Decision 1: personal API keys.


class TestPersonalApiKeys:
    def test_member_mints_a_key_within_the_member_scopes(self, client, role, store):
        r = client.post("/api/keys", json={"name": "cli", "scopes": ["read", "query", "execute"]})
        assert r.status_code == 200, r.text
        assert r.json()["raw_key"] == "sp_raw"
        store.create_api_key.assert_awaited_once_with("cli", ["read", "query", "execute"], expires_at=None)

    @pytest.mark.parametrize("scope", ["write", "admin", "dbt_proxy", "agent:run"])
    def test_member_cannot_mint_an_elevated_scope(self, client, role, store, scope):
        r = client.post("/api/keys", json={"name": "cli", "scopes": ["read", scope]})
        assert r.status_code == 403
        assert r.json()["detail"] == "Organization admin role required"
        store.create_api_key.assert_not_awaited()

    def test_admin_still_mints_any_scope(self, client, role, store):
        role["role"] = "admin"
        r = client.post("/api/keys", json={"name": "ci", "scopes": ["read", "write", "admin"]})
        assert r.status_code == 200, r.text

    def test_member_lists_only_their_own_keys(self, client, role, store):
        r = client.get("/api/keys")
        assert r.status_code == 200
        store.list_api_keys.assert_awaited_once_with(user_id=ME)

    def test_admin_lists_every_key(self, client, role, store):
        role["role"] = "org:admin"
        r = client.get("/api/keys")
        assert r.status_code == 200
        store.list_api_keys.assert_awaited_once_with()

    def test_member_deletes_their_own_key(self, client, role, store):
        store.get_api_key.return_value = _key("k1", ME, ["read"])
        assert client.delete("/api/keys/k1").status_code == 204
        store.delete_api_key.assert_awaited_once_with("k1")

    def test_member_cannot_delete_another_users_key(self, client, role, store):
        store.get_api_key.return_value = _key("k2", OTHER, ["read"])
        r = client.delete("/api/keys/k2")
        assert r.status_code == 403
        assert r.json()["detail"] == OWNERSHIP_DENIAL
        store.delete_api_key.assert_not_awaited()

    def test_admin_deletes_any_key(self, client, role, store):
        role["role"] = "admin"
        store.get_api_key.return_value = _key("k2", OTHER, ["read"])
        assert client.delete("/api/keys/k2").status_code == 204

    def test_unknown_key_is_404_for_everyone(self, client, role, store):
        assert client.delete("/api/keys/nope").status_code == 404

    def test_api_key_principal_mints_only_within_its_own_scopes(self):
        auth = {"auth_method": "api_key", "scopes": ["read", "query"]}
        keys_api._check_member_scopes(["read", "query"], auth)
        with pytest.raises(HTTPException) as exc:
            keys_api._check_member_scopes(["read", "execute"], auth)
        assert exc.value.status_code == 403
        assert exc.value.detail == "Insufficient scope"

    @pytest.mark.parametrize("method", ["notebook_session", "mcp_agent"])
    def test_run_scoped_tokens_cannot_mint_keys(self, method):
        request = SimpleNamespace(state=SimpleNamespace(auth={"auth_method": method, "scopes": ["read", "write"]}))
        with pytest.raises(HTTPException) as exc:
            keys_api._require_minting_principal(request)
        assert exc.value.status_code == 403


# Decision 2: knowledge proposals.


class TestKnowledgeProposals:
    BODY = {"scope": "org", "scope_ref": None, "category": "rules", "title": "my-rules", "body": "Always do X."}

    def test_member_proposal_is_inserted_pending_never_upserted(self, client, role, store, monkeypatch):
        from tests.test_knowledge_api import _make_doc

        store.insert_knowledge_doc.return_value = _make_doc(status="pending")
        r = client.post("/api/knowledge", json=self.BODY)
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "pending"
        store.insert_knowledge_doc.assert_awaited_once()
        assert store.insert_knowledge_doc.await_args.kwargs == {"user_id": ME, "force_pending": True}
        store.upsert_knowledge_doc.assert_not_awaited()

    def test_admin_publishes_through_the_upsert(self, client, role, store):
        from tests.test_knowledge_api import _make_doc

        role["role"] = "admin"
        store.upsert_knowledge_doc.return_value = _make_doc()
        r = client.post("/api/knowledge", json=self.BODY)
        assert r.status_code == 201, r.text
        store.upsert_knowledge_doc.assert_awaited_once()
        store.insert_knowledge_doc.assert_not_awaited()

    def test_mcp_propose_needs_write_and_archive_stays_admin(self):
        from gateway.mcp.audit import MCP_TOOL_SCOPES

        assert MCP_TOOL_SCOPES["propose_knowledge"] == "write"
        assert MCP_TOOL_SCOPES["archive_knowledge"] == "admin"

    @pytest.mark.asyncio
    async def test_store_force_pending_overrides_the_auto_accept_category(self, monkeypatch):
        from gateway.models.knowledge import KnowledgeCategory, KnowledgeDocCreate, KnowledgeScope
        from gateway.store import knowledge as knowledge_mod

        added: list = []
        session = AsyncMock()
        session.add = MagicMock(side_effect=added.append)
        result = MagicMock()
        result.scalar.return_value = 0
        session.execute = AsyncMock(return_value=result)
        monkeypatch.setattr(knowledge_mod, "_row_to_doc", lambda row, include_body=True: row)
        payload = KnowledgeDocCreate(
            scope=KnowledgeScope.org, category=KnowledgeCategory.rules, title="auto-accepted", body="x"
        )
        row = await knowledge_mod.insert_knowledge_doc(
            session,
            org_id="o",
            payload=payload,
            user_id="u",
            agent=None,
            limits=SimpleNamespace(knowledge_storage_mb=0),
            settings=None,
            force_pending=True,
        )
        assert row.status == "pending"
        assert added == [row]


# Bootstrap and /api/me expose the permission set.


class TestPermissionExposure:
    def test_me_reports_member_role_and_permissions(self, client, role):
        r = client.get("/api/me")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "member"
        assert body["is_admin"] is False
        assert body["permissions"] == sorted(MEMBER_PERMISSIONS)
        assert set(body) == {"user_id", "org_id", "role", "is_admin", "permissions", "entitlement", "capabilities"}

    def test_me_reports_admin_role_and_permissions(self, client, role):
        role["role"] = "admin"
        body = client.get("/api/me").json()
        assert body["role"] == "admin"
        assert body["is_admin"] is True
        assert body["permissions"] == sorted(ADMIN_PERMISSIONS)

    def test_bootstrap_carries_role_and_permissions(self, client, role, store, monkeypatch):
        monkeypatch.setattr("gateway.api.chat_routes.projects.standalone_chat_enabled", lambda: False)
        r = client.get("/api/chat/bootstrap")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "member"
        assert body["permissions"] == sorted(MEMBER_PERMISSIONS)
        assert body["is_admin"] is False


# Creator-or-admin on saved chat reports.


def _report_store(owner: str | None, caller: str = ME) -> MagicMock:
    store = MagicMock()
    store.user_id = caller
    store._require_org_id.return_value = "test-org"
    result = MagicMock()
    result.scalar_one_or_none.return_value = owner
    store.session.execute = AsyncMock(return_value=result)
    return store


class TestChatReportOwnership:
    @pytest.mark.asyncio
    async def test_owner_acts_as_themselves(self):
        assert await report_actor(_report_store(ME), "basic_member", report_id="r") == ME
        assert await version_actor(_report_store(ME), "basic_member", version_id="v") == ME

    @pytest.mark.asyncio
    async def test_other_member_is_refused_with_the_ownership_detail(self):
        with pytest.raises(HTTPException) as exc:
            await report_actor(_report_store(OTHER), "basic_member", report_id="r")
        assert (exc.value.status_code, exc.value.detail) == (403, OWNERSHIP_DENIAL)
        with pytest.raises(HTTPException) as exc:
            await version_actor(_report_store(OTHER), "basic_member", version_id="v")
        assert (exc.value.status_code, exc.value.detail) == (403, OWNERSHIP_DENIAL)

    @pytest.mark.asyncio
    async def test_admin_acts_on_the_owners_behalf(self):
        assert await report_actor(_report_store(OTHER), "admin", report_id="r") == OTHER
        assert await version_actor(_report_store(OTHER), "org:admin", version_id="v") == OTHER

    @pytest.mark.asyncio
    async def test_unknown_report_is_404_even_for_admins(self):
        with pytest.raises(HTTPException) as exc:
            await report_actor(_report_store(None), "admin", report_id="r")
        assert exc.value.status_code == 404


# Decision 6: production-branch writes.


class TestProductionBranchWrites:
    PROJECT = SimpleNamespace(default_branch="main")

    def test_member_cannot_write_the_default_branch(self):
        with pytest.raises(HTTPException) as exc:
            _require_branch_write(self.PROJECT, "main", "basic_member")
        assert (exc.value.status_code, exc.value.detail) == (403, "Organization admin role required")

    def test_member_writes_other_branches(self):
        assert _require_branch_write(self.PROJECT, "signalpilot-agent/x", "basic_member") == "signalpilot-agent/x"

    def test_admin_writes_the_default_branch(self):
        assert _require_branch_write(self.PROJECT, "main", "admin") == "main"

    def test_default_branch_follows_the_project_setting(self):
        project = SimpleNamespace(default_branch="production")
        assert _require_branch_write(project, "main", "basic_member") == "main"
        with pytest.raises(HTTPException):
            _require_branch_write(project, "production", "basic_member")

    def test_invalid_branch_is_still_a_400(self):
        with pytest.raises(HTTPException) as exc:
            _require_branch_write(self.PROJECT, "../x", "admin")
        assert exc.value.status_code == 400


# Creator-or-admin on Xata branch deletion.


class TestXataBranchOwnership:
    @staticmethod
    def _store() -> MagicMock:
        store = MagicMock()
        store.org_id = "test-org"
        store.user_id = ME
        store.get_credential_extras = AsyncMock(return_value={"xata_project": "p"})
        return store

    @staticmethod
    def _run(role: str, owner: str | None):
        from gateway.api.schema import exploration

        client = MagicMock()
        client.list_branches = AsyncMock(return_value=[{"name": "feature", "id": "b1"}])
        client.delete_branch = AsyncMock()
        control = MagicMock()
        control.__aenter__ = AsyncMock(return_value=client)
        control.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(exploration, "require_connection", AsyncMock(return_value=SimpleNamespace(db_type="xata"))),
            patch.object(exploration, "_require_xata_scope", lambda *a, **k: None),
            patch.object(exploration, "is_pinned", lambda extras: False),
            patch.object(exploration, "_xata_control_from_extras", lambda extras: control),
            patch.object(exploration.branch_owners, "get_branch_owner", AsyncMock(return_value=owner)),
            patch.object(exploration.branch_owners, "forget_branch_owner", AsyncMock()) as forget,
        ):
            import asyncio

            store = TestXataBranchOwnership._store()
            coro = exploration.delete_xata_branch(name="conn", store=store, role=role, project="p", branch="feature")
            try:
                result = asyncio.run(coro)
            except HTTPException as exc:
                return exc, client, forget
            return result, client, forget

    def test_creator_deletes_their_branch_and_the_record_goes_with_it(self):
        result, client, forget = self._run("basic_member", ME)
        assert result == {"status": "deleted", "branch": "feature"}
        client.delete_branch.assert_awaited_once_with("p", "b1")
        forget.assert_awaited_once()

    def test_other_member_is_refused(self):
        exc, client, _ = self._run("basic_member", OTHER)
        assert (exc.status_code, exc.detail) == (403, OWNERSHIP_DENIAL)
        client.delete_branch.assert_not_awaited()

    def test_branch_without_a_record_needs_an_admin(self):
        exc, client, _ = self._run("basic_member", None)
        assert (exc.status_code, exc.detail) == (403, "Organization admin role required")
        client.delete_branch.assert_not_awaited()

    def test_admin_deletes_any_branch(self):
        result, client, _ = self._run("admin", OTHER)
        assert result["status"] == "deleted"
        client.delete_branch.assert_awaited_once()

    def test_create_records_the_creator(self):
        import asyncio

        from gateway.api.schema import exploration

        client = MagicMock()
        client.create_child_branch = AsyncMock(return_value={"id": "b2", "name": "feature"})
        control = MagicMock()
        control.__aenter__ = AsyncMock(return_value=client)
        control.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(exploration, "require_connection", AsyncMock(return_value=SimpleNamespace(db_type="xata"))),
            patch.object(exploration, "_require_xata_scope", lambda *a, **k: None),
            patch.object(exploration, "is_pinned", lambda extras: False),
            patch.object(exploration, "_xata_control_from_extras", lambda extras: control),
            patch.object(exploration.branch_owners, "record_branch_owner", AsyncMock()) as record,
        ):
            store = self._store()
            body = exploration.XataBranchCreate(branch_name="feature", parent_id="main")
            result = asyncio.run(exploration.create_xata_branch(name="conn", store=store, body=body, project="p"))
        assert result == {"id": "b2", "name": "feature"}
        record.assert_awaited_once_with(
            store.session, org_id="test-org", connection_name="conn", project="p", branch="feature", user_id=ME
        )
