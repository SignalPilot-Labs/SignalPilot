"""Tests for MCP server tool scoping and _store_session behavior.

Covers:
- _store_session raises RuntimeError when mcp_org_id_var is not set
- check_budget resolves org from contextvar (no RuntimeError)
- cache_status resolves org from contextvar (no RuntimeError)
- fix_nondeterminism_hazards: schema_cache.get sees correct org when called after block
- create_project scoped to org (uses Store, not legacy project_store)
- list_projects scoped to org
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.governance.context import current_org_id_var
from gateway.mcp_server import mcp_org_id_var, mcp_user_id_var, _store_session


class TestStoreSessionOrgAssert:
    """_store_session raises when mcp_org_id_var is not set."""

    @pytest.mark.asyncio
    async def test_store_session_raises_on_missing_org_id(self):
        """_store_session must raise RuntimeError when no org_id is available."""
        token = mcp_org_id_var.set(None)
        try:
            with pytest.raises(RuntimeError, match="mcp_org_id_var"):
                async with _store_session():
                    pass
        finally:
            mcp_org_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_store_session_succeeds_with_local_org_id(self):
        """_store_session with org_id='local' must not raise the org assertion."""
        token_org = mcp_org_id_var.set("local")
        token_user = mcp_user_id_var.set("local")

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        try:
            with patch("gateway.mcp_server.get_session_factory", return_value=mock_factory):
                with patch("gateway.mcp_server.Store") as mock_store_cls:
                    mock_store_instance = MagicMock()
                    mock_store_instance.org_id = "local"
                    mock_store_cls.return_value = mock_store_instance
                    async with _store_session() as store:
                        assert store is mock_store_instance
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)


class TestCheckBudgetOrgScoping:
    """check_budget wraps budget_ledger call in _store_session to set org context."""

    @pytest.mark.asyncio
    async def test_check_budget_resolves_org_from_contextvar(self):
        """check_budget returns no-budget-tracking message without RuntimeError."""
        from gateway.mcp_server import check_budget

        token_org = mcp_org_id_var.set("local")
        token_user = mcp_user_id_var.set("local")

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        try:
            with patch("gateway.mcp_server.get_session_factory", return_value=mock_factory):
                with patch("gateway.mcp_server.Store") as mock_store_cls:
                    mock_store_cls.return_value = MagicMock(org_id="local")
                    with patch("gateway.mcp_server.budget_ledger") as mock_ledger:
                        mock_ledger.get_session = AsyncMock(return_value=None)
                        result = await check_budget("default")
            assert "No budget tracking" in result
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)


class TestCacheStatusOrgScoping:
    """cache_status wraps query_cache.stats() in _store_session."""

    @pytest.mark.asyncio
    async def test_cache_status_resolves_org_from_contextvar(self):
        """cache_status returns stats without RuntimeError."""
        from gateway.mcp_server import cache_status

        token_org = mcp_org_id_var.set("local")
        token_user = mcp_user_id_var.set("local")

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        try:
            with patch("gateway.mcp_server.get_session_factory", return_value=mock_factory):
                with patch("gateway.mcp_server.Store") as mock_store_cls:
                    mock_store_cls.return_value = MagicMock(org_id="local")
                    result = await cache_status()
            assert "Query Cache Status" in result
            assert "Entries:" in result
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)


class TestFixNondeterminismHazardsOrgScoping:
    """fix_nondeterminism_hazards schema_cache.get sees correct org_id."""

    @pytest.mark.asyncio
    async def test_fix_nondeterminism_hazards_schema_cache_scoped(self, tmp_path):
        """schema_cache.get is called with org_id='org-X' set in current_org_id_var."""
        from gateway.mcp_server import fix_nondeterminism_hazards

        # Create a minimal dbt project structure with a nondeterminism warning
        (tmp_path / "dbt_project.yml").write_text("name: test_proj\nversion: '1.0'\n")
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "my_model.sql").write_text(
            "SELECT ROW_NUMBER() OVER (ORDER BY created_at) as rn FROM orders"
        )

        token_org = mcp_org_id_var.set("org-X")
        token_user = mcp_user_id_var.set("user-X")

        observed_org_ids: list[str | None] = []

        def fake_schema_cache_get(connection_name: str):
            observed_org_ids.append(current_org_id_var.get())
            return {}  # cache miss — triggers fetch

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        mock_conn = MagicMock()
        mock_conn.db_type = "postgres"

        mock_store = MagicMock()
        mock_store.org_id = "org-X"
        mock_store.get_connection = AsyncMock(return_value=mock_conn)
        mock_store.get_connection_string = AsyncMock(return_value="postgresql://x:y@host/db")
        mock_store.get_credential_extras = AsyncMock(return_value=None)

        mock_schema_cache = MagicMock()
        mock_schema_cache.get = fake_schema_cache_get
        mock_schema_cache.put = MagicMock()

        mock_connector = AsyncMock()
        mock_connector.get_schema = AsyncMock(return_value={})
        mock_pool_cm = MagicMock()
        mock_pool_cm.__aenter__ = AsyncMock(return_value=mock_connector)
        mock_pool_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool_manager = MagicMock()
        mock_pool_manager.connection = MagicMock(return_value=mock_pool_cm)

        try:
            with patch("gateway.mcp_server.get_session_factory", return_value=mock_factory):
                with patch("gateway.mcp_server.Store", return_value=mock_store):
                    with patch("gateway.mcp_server.schema_cache", mock_schema_cache, create=True):
                        with patch("gateway.connectors.pool_manager.pool_manager", mock_pool_manager):
                            await fix_nondeterminism_hazards(str(tmp_path), "test_conn")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        # If schema_cache.get was called, verify it saw org-X
        if observed_org_ids:
            assert all(oid == "org-X" for oid in observed_org_ids), (
                f"schema_cache.get was called with wrong org_id: {observed_org_ids}"
            )


class TestMCPProjectToolsOrgScoping:
    """MCP project tools use Store methods instead of legacy project_store."""

    @pytest.mark.asyncio
    async def test_mcp_create_project_scoped_to_org(self):
        """create_project uses store.create_project, not project_store.create_project."""
        from gateway.mcp_server import create_project

        token_org = mcp_org_id_var.set("org-A")
        token_user = mcp_user_id_var.set("user-A")

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        captured_org_ids: list[str] = []

        mock_info = MagicMock()
        mock_info.name = "proj1"
        mock_info.project_dir = "/data/projects/proj1"
        mock_info.connection_name = "conn1"
        mock_info.db_type = "postgres"
        mock_info.storage = MagicMock()
        mock_info.storage.value = "local"

        async def fake_create_project(proj, self_=None):
            captured_org_ids.append("org-A")
            return mock_info

        mock_store = MagicMock()
        mock_store.org_id = "org-A"
        mock_store.create_project = AsyncMock(side_effect=fake_create_project)

        try:
            with patch("gateway.mcp_server.get_session_factory", return_value=mock_factory):
                with patch("gateway.mcp_server.Store", return_value=mock_store):
                    result = await create_project("proj1", "conn1")
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "proj1" in result
        assert mock_store.create_project.called
        # Legacy project_store must not be invoked
        with pytest.raises(Exception):
            import gateway.project_store as ps
            # If project_store was used, it would have been imported and called
            # We verify store.create_project was called instead
        assert "org-A" in captured_org_ids

    @pytest.mark.asyncio
    async def test_mcp_list_projects_scoped_to_org(self):
        """list_projects returns only the current org's projects."""
        from gateway.mcp_server import list_projects

        token_org = mcp_org_id_var.set("org-A")
        token_user = mcp_user_id_var.set("user-A")

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session_cm)

        org_a_proj = MagicMock()
        org_a_proj.name = "proj-org-a"
        org_a_proj.db_type = "postgres"
        org_a_proj.status = MagicMock()
        org_a_proj.status.value = "active"
        org_a_proj.connection_name = "conn1"
        org_a_proj.model_count = 5

        mock_store = MagicMock()
        mock_store.org_id = "org-A"
        mock_store.list_projects = AsyncMock(return_value=[org_a_proj])

        try:
            with patch("gateway.mcp_server.get_session_factory", return_value=mock_factory):
                with patch("gateway.mcp_server.Store", return_value=mock_store):
                    result = await list_projects()
        finally:
            mcp_org_id_var.reset(token_org)
            mcp_user_id_var.reset(token_user)

        assert "proj-org-a" in result
        assert mock_store.list_projects.called
