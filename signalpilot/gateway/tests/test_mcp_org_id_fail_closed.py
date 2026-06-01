"""Tests for APP-I-5: fail-closed MCP org-id gating in cloud mode."""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# TestRequireMcpOrgId
# ---------------------------------------------------------------------------


class TestRequireMcpOrgId:
    def test_cloud_mode_missing_org_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        from gateway.mcp.context import mcp_org_id_var, require_mcp_org_id

        token = mcp_org_id_var.set(None)
        try:
            with pytest.raises(RuntimeError, match="mcp_org_id_var is unset"):
                require_mcp_org_id()
        finally:
            mcp_org_id_var.reset(token)

    def test_cloud_mode_present_org_returns_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        from gateway.mcp.context import mcp_org_id_var, require_mcp_org_id

        token = mcp_org_id_var.set("org-abc")
        try:
            assert require_mcp_org_id() == "org-abc"
        finally:
            mcp_org_id_var.reset(token)

    def test_local_mode_missing_org_returns_local_literal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        from gateway.mcp.context import mcp_org_id_var, require_mcp_org_id

        token = mcp_org_id_var.set(None)
        try:
            assert require_mcp_org_id() == "local"
        finally:
            mcp_org_id_var.reset(token)


# ---------------------------------------------------------------------------
# TestRequireMcpUserId
# ---------------------------------------------------------------------------


class TestRequireMcpUserId:
    def test_cloud_mode_missing_user_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        from gateway.mcp.context import mcp_user_id_var, require_mcp_user_id

        token = mcp_user_id_var.set(None)
        try:
            with pytest.raises(RuntimeError, match="mcp_user_id_var is unset"):
                require_mcp_user_id()
        finally:
            mcp_user_id_var.reset(token)

    def test_cloud_mode_present_user_returns_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        from gateway.mcp.context import mcp_user_id_var, require_mcp_user_id

        token = mcp_user_id_var.set("user-xyz")
        try:
            assert require_mcp_user_id() == "user-xyz"
        finally:
            mcp_user_id_var.reset(token)

    def test_local_mode_missing_user_returns_local_literal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        from gateway.mcp.context import mcp_user_id_var, require_mcp_user_id

        token = mcp_user_id_var.set(None)
        try:
            assert require_mcp_user_id() == "local"
        finally:
            mcp_user_id_var.reset(token)


# ---------------------------------------------------------------------------
# TestRunNotebookOrgGuard — integration smoke for highest-blast-radius tool
# ---------------------------------------------------------------------------


class TestRunNotebookOrgGuard:
    @pytest.mark.asyncio
    async def test_cloud_mode_missing_org_returns_error_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var
        from gateway.mcp.tools.notebook import run_notebook

        org_token = mcp_org_id_var.set(None)
        user_token = mcp_user_id_var.set(None)
        try:
            result = await run_notebook(
                filename="analysis.py",
                code="print('hello')",
                project_id="proj-1",
                agent_branch="",
            )
        finally:
            mcp_org_id_var.reset(org_token)
            mcp_user_id_var.reset(user_token)

        assert isinstance(result, str)
        assert result.startswith("Error: ")

    @pytest.mark.asyncio
    async def test_local_mode_missing_org_proceeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In local mode the guard returns 'local' and doesn't raise.

        Downstream _store_session is mocked to short-circuit execution so the
        test doesn't need a real DB. The important invariant is that no
        RuntimeError escapes from the require_mcp_org_id/require_mcp_user_id guard.
        """
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var

        org_token = mcp_org_id_var.set(None)
        user_token = mcp_user_id_var.set(None)
        try:
            # Patch _validate_filename to return an error so the tool exits early
            # after the guard succeeds, without touching _store_session or k8s.
            with patch(
                "gateway.mcp.tools.notebook._validate_filename",
                return_value="Error: short-circuit for test",
            ):
                from gateway.mcp.tools.notebook import run_notebook

                result = await run_notebook(
                    filename="analysis.py",
                    code="print('hello')",
                    project_id="proj-1",
                    agent_branch="",
                )
        finally:
            mcp_org_id_var.reset(org_token)
            mcp_user_id_var.reset(user_token)

        # The result is a string (not a raised RuntimeError)
        assert isinstance(result, str)
        # Guard passed — result comes from the short-circuit, not from the org guard
        assert "mcp_org_id_var" not in result
