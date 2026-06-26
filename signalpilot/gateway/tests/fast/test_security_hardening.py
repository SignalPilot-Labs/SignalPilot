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
