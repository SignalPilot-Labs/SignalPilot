"""Tests for APP-M-1: cross-org GitHub repo-link IDOR prevention.

Covers two fix sites:
1. store/github.py::create_repo_link — raises ProjectNotFoundError for foreign project.
2. git/sync.py::sync_project_with_github — returns {"error": "Project not found"} for foreign project.

And the API translation:
3. api/github.py::create_repo_link — translates ProjectNotFoundError → 404.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.api.deps import get_store
from gateway.db.models import GatewayBase, GatewayGitHubRepoLink, GatewayWorkspaceProject
from gateway.store import github as gh_store

# ─── Shared DB fixture ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite async session scoped per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_project(org_id: str, project_id: str | None = None) -> GatewayWorkspaceProject:
    now = time.time()
    return GatewayWorkspaceProject(
        id=project_id or str(uuid.uuid4()),
        org_id=org_id,
        name=f"proj-{uuid.uuid4().hex[:8]}",
        display_name="Test Project",
        source="managed",
        status="active",
        file_count=0,
        total_bytes=0,
        created_at=now,
        updated_at=now,
    )


# ─── TestGitHubRepoLinkOrgIsolation ──────────────────────────────────────────


class TestGitHubRepoLinkOrgIsolation:
    # ── Test 1: create_repo_link rejects foreign project ─────────────────────

    @pytest.mark.asyncio
    async def test_create_repo_link_rejects_foreign_project(self, db_session: AsyncSession):
        """create_repo_link with org_A and a project owned by org_B raises ProjectNotFoundError."""
        project = _make_project("org_B")
        db_session.add(project)
        await db_session.commit()

        with pytest.raises(gh_store.ProjectNotFoundError):
            await gh_store.create_repo_link(
                db_session,
                org_id="org_A",
                project_id=project.id,
                installation_id="inst-1",
                repo_full_name="acme/repo",
                repo_id=42,
                default_branch="main",
            )

        # No link row should exist.
        result = await db_session.execute(select(GatewayGitHubRepoLink))
        assert result.scalars().all() == []

    # ── Test 2: create_repo_link accepts same-org project ────────────────────

    @pytest.mark.asyncio
    async def test_create_repo_link_accepts_same_org_project(self, db_session: AsyncSession):
        """create_repo_link with matching org_id succeeds (regression guard)."""
        project = _make_project("org_B")
        db_session.add(project)
        await db_session.commit()

        link = await gh_store.create_repo_link(
            db_session,
            org_id="org_B",
            project_id=project.id,
            installation_id="inst-1",
            repo_full_name="acme/repo",
            repo_id=42,
            default_branch="main",
        )

        assert link.project_id == project.id
        assert link.org_id == "org_B"

        result = await db_session.execute(select(GatewayGitHubRepoLink))
        rows = result.scalars().all()
        assert len(rows) == 1

    # ── Test 3: sync_project_with_github rejects foreign project ─────────────

    @pytest.mark.asyncio
    async def test_sync_project_with_github_rejects_foreign_project(self, db_session: AsyncSession):
        """sync_project_with_github for a project owned by org_B, called with org_A,
        returns {"error": "Project not found"} and never calls list_branches/push_branch."""
        from gateway.git.sync import sync_project_with_github

        # Seed a project and repo link owned by org_B.
        project = _make_project("org_B")
        db_session.add(project)
        await db_session.commit()

        now = time.time()
        link_row = GatewayGitHubRepoLink(
            id=str(uuid.uuid4()),
            org_id="org_B",
            project_id=project.id,
            installation_id="inst-1",
            repo_full_name="acme/repo",
            repo_id=42,
            default_branch="main",
            status="active",
            created_at=now,
            updated_at=now,
        )
        db_session.add(link_row)
        await db_session.commit()

        # Patch the session factory to return our test session.
        mock_factory = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        with (
            patch("gateway.git.sync.list_branches") as mock_list,
            patch("gateway.git.sync.push_branch") as mock_push,
            patch("gateway.db.engine.get_session_factory", return_value=mock_factory),
        ):
            result = await sync_project_with_github(project.id, "org_A")

        assert result == {"error": "Project not found"}
        mock_list.assert_not_called()
        mock_push.assert_not_called()

    # ── Test 4: API handler returns 404 for foreign project ──────────────────

    def test_api_create_repo_link_returns_404_for_foreign_project(self):
        """POST /api/github/repo-links with a project belonging to a different org returns 404."""
        from gateway.main import app

        # Build a minimal fake store with org_A identity.
        fake_store = MagicMock()
        fake_store.org_id = "org_A"
        fake_store.user_id = "user-1"
        fake_store.session = MagicMock()

        async def _fake_get_store() -> Any:
            return fake_store

        # Bypass RequireScope by injecting auth into request state.
        class _BypassAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: Any) -> Any:
                request.state.auth = {
                    "auth_method": "api_key",
                    "user_id": "user-1",
                    "scopes": ["write"],
                }
                return await call_next(request)

        # Patch create_repo_link in the store module to raise ProjectNotFoundError.
        app.dependency_overrides[get_store] = _fake_get_store

        project_id = str(uuid.uuid4())

        try:
            with (
                patch("gateway.store.github.create_repo_link", new_callable=AsyncMock) as mock_create,
                patch("gateway.main.init_db", new_callable=AsyncMock),
                patch("gateway.main.close_db", new_callable=AsyncMock),
                patch("gateway.main.get_session_factory", return_value=MagicMock()),
                patch("gateway.auth.jwt_secret.load_session_jwt_secret"),
                patch("gateway.git.repos.ensure_repos_dir"),
                patch("gateway.main.health_monitor.load_from_db", new_callable=AsyncMock),
            ):
                mock_create.side_effect = gh_store.ProjectNotFoundError(project_id)

                client = TestClient(app, raise_server_exceptions=False)
                with client:
                    # Patch the APIKeyAuthMiddleware dispatch to inject auth state.
                    from gateway.http import APIKeyAuthMiddleware

                    current = app.middleware_stack
                    while current is not None:
                        if isinstance(current, APIKeyAuthMiddleware):
                            current.dispatch_func = _BypassAuthMiddleware(app).dispatch
                            break
                        current = getattr(current, "app", None)

                    response = client.post(
                        "/api/github/repo-links",
                        json={
                            "project_id": project_id,
                            "installation_id": "inst-1",
                            "repo_full_name": "acme/repo",
                            "repo_id": 42,
                            "default_branch": "main",
                        },
                    )

                assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_store, None)
