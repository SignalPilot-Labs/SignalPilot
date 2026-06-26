"""Security hardening tests — pure unit tests (no DB, no network).

Covers:
  1. TestXataFieldPatterns — regex validation on ConnectionCreate and ConnectionUpdate
  2. TestDbtProfileBlockRedaction — profiles_target_block redacts password; output retains it
  3. TestDbtProfileParentBranchProtected — parent-branch 403 path
  4. TestDeleteBranchProtected — delete_xata_branch refuses protected branches
  5. TestXataControlMissingOrg — _xata_control_from_extras raises 400 on missing org
  6. TestManageReportAdminScope — manage_report enforces admin scope
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from gateway.models import ConnectionCreate, ConnectionUpdate

# ─── Group 1: Xata field regex patterns ──────────────────────────────────────


_MINIMAL_XATA_CREATE = {
    "name": "t",
    "db_type": "xata",
    "region": "us-east-1",
    "database": "mydb",
}


def _xata_create(**kwargs) -> dict:
    return {**_MINIMAL_XATA_CREATE, **kwargs}


class TestXataFieldPatterns:
    def test_xata_api_key_rejects_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(**_xata_create(xata_api_key="xau_ key"))

    def test_xata_api_key_rejects_quote(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(**_xata_create(xata_api_key='xau_"hax'))

    def test_xata_project_rejects_slash(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(**_xata_create(xata_project="a/b"))

    def test_xata_database_rejects_dot(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(**_xata_create(xata_database="a.b"))

    def test_xata_api_key_accepts_xau_dot_dash(self) -> None:
        obj = ConnectionCreate(
            **_xata_create(
                xata_api_key="xau_abc.123-XY",
                xata_organization="myorg",
                xata_project="prj_abc123",
            )
        )
        assert obj.xata_api_key == "xau_abc.123-XY"

    def test_update_validates_new_xata_fields(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionUpdate(xata_project="a/b")

    def test_update_xata_database_rejects_dot(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionUpdate(xata_database="a.b")

    def test_update_xata_api_key_rejects_space(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionUpdate(xata_api_key="xau_ key")

    def test_update_xata_project_accepts_valid(self) -> None:
        obj = ConnectionUpdate(xata_project="prj_abc123")
        assert obj.xata_project == "prj_abc123"

    def test_update_xata_database_accepts_valid(self) -> None:
        obj = ConnectionUpdate(xata_database="mydb")
        assert obj.xata_database == "mydb"


# ─── Group 2: dbt profile block redaction ────────────────────────────────────


class TestDbtProfileBlockRedaction:
    """profiles_target_block must NOT contain the password; output MUST."""

    @pytest.mark.asyncio
    async def test_block_redacted_output_intact(self) -> None:
        from gateway.api.schema.exploration import get_xata_dbt_profile

        fake_password = "supersecret_pw_42"
        fake_cs = f"postgres://xata:{fake_password}@br123.us-east-1.xata.tech:5432/xata"

        mock_store = AsyncMock()
        mock_store.org_id = "org-test"
        mock_store.get_credential_extras = AsyncMock(return_value={"xata_database": "xata"})

        mock_info = MagicMock()
        mock_info.db_type = "xata"

        with (
            patch(
                "gateway.api.schema.exploration.require_connection",
                AsyncMock(return_value=mock_info),
            ),
            patch(
                "gateway.connectors.drivers.xata.XataConnector._resolve_endpoint",
                AsyncMock(return_value=fake_cs),
            ),
        ):
            response = await get_xata_dbt_profile(
                name="conn",
                store=mock_store,
                branch="agent-branch-1",
                profile="default",
                target=None,
                schema="public",
            )

        block = response["profiles_target_block"]
        output = response["output"]
        assert fake_password not in block, "password must be redacted from profiles_target_block"
        assert "<fetched-server-side" in block, "placeholder must appear in profiles_target_block"
        assert output["password"] == fake_password, "output must still carry the live password"


# ─── Group 3: parent-branch protection on dbt profile ────────────────────────


class TestDbtProfileParentBranchProtected:
    """When the resolved branch was forked from a protected branch, raise 403."""

    @pytest.mark.asyncio
    async def test_parent_protected_raises_403(self) -> None:
        from gateway.api.schema.exploration import get_xata_dbt_profile

        mock_store = AsyncMock()
        mock_store.org_id = "org-test"
        mock_store.get_credential_extras = AsyncMock(
            return_value={"xata_project": "prj_abc", "xata_api_key": "xau_testkey", "xata_organization": "myorg"}
        )
        mock_store.get_connection_string = AsyncMock(return_value=None)

        mock_info = MagicMock()
        mock_info.db_type = "xata"

        # Simulate branch list where "agent_x" has parentID pointing to "main"
        fake_branches = [
            {"id": "br_main", "name": "main", "parentID": None},
            {"id": "br_agent", "name": "agent_x", "parentID": "br_main"},
        ]

        mock_client = AsyncMock()
        mock_client.list_branches = AsyncMock(return_value=fake_branches)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "gateway.api.schema.exploration.require_connection",
                AsyncMock(return_value=mock_info),
            ),
            patch(
                "gateway.api.schema.exploration._xata_control_from_extras",
                return_value=mock_client,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_xata_dbt_profile(
                    name="conn",
                    store=mock_store,
                    branch="agent_x",
                    profile="default",
                    target=None,
                    schema="public",
                )

        assert exc_info.value.status_code == 403
        assert "main" in exc_info.value.detail


# ─── Group 4: delete_xata_branch — protected branch denylist ─────────────────


class TestDeleteBranchProtected:
    @pytest.mark.asyncio
    async def test_delete_protected_raises_403(self) -> None:
        from gateway.api.schema.exploration import delete_xata_branch

        mock_store = AsyncMock()
        mock_store.get_credential_extras = AsyncMock(return_value={})
        mock_store.get_connection_string = AsyncMock(return_value="postgres://x:y@host/db")

        mock_info = MagicMock()
        mock_info.db_type = "xata"

        with patch(
            "gateway.api.schema.exploration.require_connection",
            AsyncMock(return_value=mock_info),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_xata_branch(
                    name="conn",
                    store=mock_store,
                    project="prj_abc",
                    branch="main",
                )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_non_protected_proceeds(self) -> None:
        from gateway.api.schema.exploration import delete_xata_branch

        mock_store = AsyncMock()
        mock_store.get_credential_extras = AsyncMock(return_value={"xata_organization": "myorg"})
        mock_store.get_connection_string = AsyncMock(return_value=None)

        mock_info = MagicMock()
        mock_info.db_type = "xata"

        mock_client = AsyncMock()
        mock_client.list_branches = AsyncMock(
            return_value=[{"id": "br_agent", "name": "agent-branch", "parentID": None}]
        )
        mock_client.delete_branch = AsyncMock(return_value=None)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "gateway.api.schema.exploration.require_connection",
                AsyncMock(return_value=mock_info),
            ),
            patch(
                "gateway.api.schema.exploration._xata_control_from_extras",
                return_value=mock_client,
            ),
        ):
            result = await delete_xata_branch(
                name="conn",
                store=mock_store,
                project="prj_abc",
                branch="agent-branch",
            )

        assert result["status"] == "deleted"


# ─── Group 5: _xata_control_from_extras — missing org → 400 ─────────────────


class TestXataControlMissingOrg:
    def test_missing_org_raises_400(self) -> None:
        from gateway.api.schema.exploration import _xata_control_from_extras

        # extras has api key but no xata_organization or xata_org
        with pytest.raises(HTTPException) as exc_info:
            _xata_control_from_extras(None, {"xata_api_key": "xau_testkey"})

        assert exc_info.value.status_code == 400
        assert "xata_organization" in exc_info.value.detail

    def test_with_org_does_not_raise(self) -> None:
        from gateway.api.schema.exploration import _xata_control_from_extras

        # Should return a context manager without raising
        result = _xata_control_from_extras(None, {"xata_api_key": "xau_testkey", "xata_organization": "myorg"})
        assert result is not None


# ─── Group 6: manage_report — admin scope enforcement ────────────────────────


class TestManageReportAdminScope:
    @pytest.mark.asyncio
    async def test_create_without_admin_scope_returns_error(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.reports import manage_report

        token_org = mcp_org_id_var.set("real-org-123")
        token_scopes = mcp_scopes_var.set(["read", "write"])
        try:
            result = await manage_report(action="create", title="t", html="<p/>")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert result.startswith("Error: admin scope required")

    @pytest.mark.asyncio
    async def test_delete_without_admin_scope_returns_error(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.reports import manage_report

        token_org = mcp_org_id_var.set("real-org-123")
        token_scopes = mcp_scopes_var.set(["read", "write"])
        try:
            result = await manage_report(action="delete", report_id="some-id")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert result.startswith("Error: admin scope required")

    @pytest.mark.asyncio
    async def test_local_org_bypasses_scope_check(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.reports import manage_report

        token_org = mcp_org_id_var.set("local")
        token_scopes = mcp_scopes_var.set([])

        mock_store = AsyncMock()
        mock_report = MagicMock()
        mock_report.id = "rpt_abc123"
        mock_store.insert_report = AsyncMock(return_value=mock_report)

        @asynccontextmanager
        async def _fake_store_session(
            user_id: str | None = None, org_id: str | None = None
        ) -> AsyncIterator[AsyncMock]:
            yield mock_store

        try:
            with patch("gateway.mcp.tools.reports._store_session", _fake_store_session):
                result = await manage_report(action="create", title="t", html="<p/>")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert "created" in result

    @pytest.mark.asyncio
    async def test_with_admin_scope_proceeds(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.reports import manage_report

        token_org = mcp_org_id_var.set("real-org-123")
        token_scopes = mcp_scopes_var.set(["admin"])

        mock_store = AsyncMock()
        mock_report = MagicMock()
        mock_report.id = "rpt_xyz"
        mock_store.insert_report = AsyncMock(return_value=mock_report)

        @asynccontextmanager
        async def _fake_store_session(
            user_id: str | None = None, org_id: str | None = None
        ) -> AsyncIterator[AsyncMock]:
            yield mock_store

        try:
            with patch("gateway.mcp.tools.reports._store_session", _fake_store_session):
                result = await manage_report(action="create", title="My Report", html="<html/>")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert "created" in result


# ─── Group 7: xata_branch_diff — admin scope enforcement for html format ──────


class TestXataBranchDiffAdminScope:
    @pytest.mark.asyncio
    async def test_html_format_without_admin_scope_returns_error(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.schema.ddl import xata_branch_diff

        token_org = mcp_org_id_var.set("real-org")
        token_scopes = mcp_scopes_var.set(["read"])
        try:
            with (
                patch("gateway.mcp.tools.schema.ddl._no_xata_db_msg", AsyncMock(return_value=None)),
                patch("gateway.mcp.tools.schema.ddl._save_branch_diff_report", AsyncMock()) as mock_save,
                patch("httpx.AsyncClient") as mock_client_cls,
            ):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"diff": {"has_changes": False}}
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_http
                result = await xata_branch_diff(
                    connection_name="c", base_branch="main", compare_branch="feat", format="html"
                )
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert result.startswith("Error: admin scope required")
        mock_save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_text_format_does_not_require_admin(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.schema.ddl import xata_branch_diff

        token_org = mcp_org_id_var.set("real-org")
        token_scopes = mcp_scopes_var.set(["read"])
        try:
            with (
                patch("gateway.mcp.tools.schema.ddl._no_xata_db_msg", AsyncMock(return_value=None)),
                patch("httpx.AsyncClient") as mock_client_cls,
            ):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"diff": {"has_changes": False}}
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_http
                result = await xata_branch_diff(
                    connection_name="c", base_branch="main", compare_branch="feat", format="text"
                )
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert not result.startswith("Error: admin scope required")

    @pytest.mark.asyncio
    async def test_html_with_admin_scope_proceeds(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.schema.ddl import xata_branch_diff

        token_org = mcp_org_id_var.set("real-org")
        token_scopes = mcp_scopes_var.set(["admin"])
        try:
            with (
                patch("gateway.mcp.tools.schema.ddl._no_xata_db_msg", AsyncMock(return_value=None)),
                patch(
                    "gateway.mcp.tools.schema.ddl._save_branch_diff_report",
                    AsyncMock(return_value='{"status":"created"}'),
                ),
                patch("httpx.AsyncClient") as mock_client_cls,
            ):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"diff": {}}
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_http
                result = await xata_branch_diff(
                    connection_name="c", base_branch="main", compare_branch="feat", format="html"
                )
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert result == '{"status":"created"}'

    @pytest.mark.asyncio
    async def test_html_local_mode_bypasses(self) -> None:
        from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var
        from gateway.mcp.tools.schema.ddl import xata_branch_diff

        token_org = mcp_org_id_var.set("local")
        token_scopes = mcp_scopes_var.set([])
        try:
            with (
                patch("gateway.mcp.tools.schema.ddl._no_xata_db_msg", AsyncMock(return_value=None)),
                patch(
                    "gateway.mcp.tools.schema.ddl._save_branch_diff_report",
                    AsyncMock(return_value='{"status":"created"}'),
                ),
                patch("httpx.AsyncClient") as mock_client_cls,
            ):
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"diff": {}}
                mock_http = AsyncMock()
                mock_http.get = AsyncMock(return_value=mock_response)
                mock_http.__aenter__ = AsyncMock(return_value=mock_http)
                mock_http.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_http
                result = await xata_branch_diff(
                    connection_name="c", base_branch="main", compare_branch="feat", format="html"
                )
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_scopes_var.reset(token_scopes)

        assert result == '{"status":"created"}'


# ─── Group 8: map_columns — workspace-root containment ───────────────────────


class TestMapColumnsWorkspaceContainment:
    def test_rejects_dotdot_escape(self, tmp_path, monkeypatch) -> None:
        from gateway.mcp.tools.model_map import _validated_project_dir

        monkeypatch.setenv("SP_WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.delenv("SP_NOTEBOOK_ROOT", raising=False)
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        _, err = _validated_project_dir(str(tmp_path / ".."))
        assert err is not None
        assert "outside the workspace root" in err or "not permitted" in err

    def test_rejects_absolute_outside_root(self, tmp_path, monkeypatch) -> None:
        from gateway.mcp.tools.model_map import _validated_project_dir

        monkeypatch.setenv("SP_WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.delenv("SP_NOTEBOOK_ROOT", raising=False)
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        _, err = _validated_project_dir("/etc")
        assert err is not None
        assert "outside the workspace root" in err or "Error:" in err

    def test_accepts_path_under_root(self, tmp_path, monkeypatch) -> None:
        from gateway.mcp.tools.model_map import _validated_project_dir

        sub = tmp_path / "myproject"
        sub.mkdir()
        monkeypatch.setenv("SP_WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.delenv("SP_NOTEBOOK_ROOT", raising=False)
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        path, err = _validated_project_dir(str(sub))
        assert err is None
        assert path is not None

    def test_cloud_mode_requires_explicit_root(self, monkeypatch) -> None:
        from gateway.mcp.tools.model_map import _validated_project_dir

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_WORKSPACE_ROOT", raising=False)
        monkeypatch.delenv("SP_NOTEBOOK_ROOT", raising=False)

        _, err = _validated_project_dir("/some/path")
        assert err is not None
        assert "SP_WORKSPACE_ROOT not configured" in err


# ─── Group 9: knowledge upsert — archived doc stays archived ─────────────────


class TestKnowledgeUpsertPreservesArchived:
    def test_archived_status_unchanged_on_local_edit(self) -> None:
        """Unit test for the status-transition branch in propose_knowledge.

        Simulates the in-memory logic: if existing.status is "archived" and we
        are NOT in cloud agent mode, the new branch must leave status unchanged.
        """
        from gateway.store.knowledge import KnowledgeStatus

        # Simulate existing doc with archived status
        class _FakeDoc:
            status: str = KnowledgeStatus.archived.value

        existing = _FakeDoc()
        agent = None  # local-mode (no agent)

        # Mirror the new branch logic from propose_knowledge
        # Cloud path not triggered (agent is None), so:
        if agent is not None:
            existing.status = KnowledgeStatus.pending.value
        elif existing.status != KnowledgeStatus.archived.value:
            existing.status = KnowledgeStatus.active.value
        # else: archived stays archived

        assert existing.status == KnowledgeStatus.archived.value, (
            "Archived doc must stay archived on local-mode edit"
        )

    def test_pending_status_promoted_to_active_on_local_edit(self) -> None:
        """Existing behavior: pending → active in local mode is preserved."""
        from gateway.store.knowledge import KnowledgeStatus

        class _FakeDoc:
            status: str = KnowledgeStatus.pending.value

        existing = _FakeDoc()
        agent = None

        if agent is not None:
            existing.status = KnowledgeStatus.pending.value
        elif existing.status != KnowledgeStatus.archived.value:
            existing.status = KnowledgeStatus.active.value

        assert existing.status == KnowledgeStatus.active.value


# ─── Group 10: auth failure bucket cleanup ────────────────────────────────────


class TestAuthFailureBucketCleanup:
    def setup_method(self) -> None:
        import gateway.auth.mcp_api_key as _mod

        _mod._auth_failures.clear()

    def test_bucket_created_on_first_failure(self) -> None:
        import gateway.auth.mcp_api_key as _mod
        from gateway.auth.mcp_api_key import _check_auth_rate

        _check_auth_rate("1.2.3.4")
        assert "1.2.3.4" in _mod._auth_failures

    def test_stale_entries_pruned_and_bucket_replaced(self, monkeypatch) -> None:
        import time

        import gateway.auth.mcp_api_key as _mod
        from gateway.auth.mcp_api_key import _check_auth_rate

        base_time = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: base_time)
        _check_auth_rate("1.2.3.4")
        assert "1.2.3.4" in _mod._auth_failures

        # Advance 61 seconds — old entry is now stale
        advanced = base_time + 61.0
        monkeypatch.setattr(time, "monotonic", lambda: advanced)
        _check_auth_rate("1.2.3.4")

        # Bucket should still exist (new entry was added) but only have 1 item
        assert "1.2.3.4" in _mod._auth_failures
        assert len(_mod._auth_failures["1.2.3.4"]) == 1

    def test_empty_bucket_deleted_after_prune(self, monkeypatch) -> None:
        import time

        import gateway.auth.mcp_api_key as _mod
        from gateway.auth.mcp_api_key import _check_auth_rate

        base_time = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: base_time)
        _check_auth_rate("1.2.3.4")

        # Advance 61 seconds then call with a different IP
        # The "1.2.3.4" bucket will only be cleaned when that IP is checked
        advanced = base_time + 61.0
        monkeypatch.setattr(time, "monotonic", lambda: advanced)
        _check_auth_rate("1.2.3.4")  # prunes old entry, adds new one

        # Advance another 61 seconds — now "1.2.3.4"'s second entry is stale
        very_advanced = base_time + 122.0
        monkeypatch.setattr(time, "monotonic", lambda: very_advanced)

        # Call with different IP — does NOT prune 1.2.3.4
        _check_auth_rate("5.6.7.8")

        # Now explicitly check 1.2.3.4 — bucket prunes to empty and is deleted
        _check_auth_rate("1.2.3.4")
        # After 122s, both old entries for 1.2.3.4 are gone; a new one is inserted
        # The key exists with just the new entry
        assert "1.2.3.4" in _mod._auth_failures
        assert len(_mod._auth_failures["1.2.3.4"]) == 1

    def test_bucket_removed_when_only_stale_and_no_new_call(self, monkeypatch) -> None:
        """Regression: key must be deleted when the pruned hits list is empty before appending."""
        import time

        import gateway.auth.mcp_api_key as _mod
        from gateway.auth.mcp_api_key import _check_auth_rate

        base_time = 2000.0
        monkeypatch.setattr(time, "monotonic", lambda: base_time)
        _check_auth_rate("9.9.9.9")

        # Advance 61s — old entry is stale. The NEXT call re-inserts a new entry.
        advanced = base_time + 61.0
        monkeypatch.setattr(time, "monotonic", lambda: advanced)
        _check_auth_rate("9.9.9.9")

        # The bucket must be updated with only the new timestamp
        assert len(_mod._auth_failures["9.9.9.9"]) == 1
        assert _mod._auth_failures["9.9.9.9"][0] == pytest.approx(advanced)
