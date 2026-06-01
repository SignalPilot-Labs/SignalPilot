"""Tests for APP-M-3: cross-org IDOR prevention in POST /api/notebook-sessions.

Covers the precheck added to create_session that verifies body.project_id belongs
to the caller's org before any side effect (session row insert, JWT mint, K8s call).
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayNotebookSession, GatewayWorkspaceProject
from gateway.models.notebook_sessions import NotebookSessionCreate

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


def _make_fake_store(db_session: AsyncSession, org_id: str, user_id: str) -> Any:
    fake_store = MagicMock()
    fake_store.org_id = org_id
    fake_store.user_id = user_id
    fake_store.session = db_session
    return fake_store


# ─── TestNotebookSessionsOrgIsolation ────────────────────────────────────────


class TestNotebookSessionsOrgIsolation:
    @pytest.mark.asyncio
    async def test_create_session_rejects_foreign_project_id(self, db_session: AsyncSession):
        """create_session with project_id owned by org_B and store org_id org_A raises HTTP 404.

        Verifies that mint_session_jwt and ns.create_session are NOT called, and that
        no GatewayNotebookSession rows are written.
        """
        from gateway.api.notebook_sessions import create_session

        project = _make_project("org_B")
        db_session.add(project)
        await db_session.commit()

        fake_store = _make_fake_store(db_session, org_id="org_A", user_id="user-1")

        mock_mint = AsyncMock()
        mock_ns_create = AsyncMock()

        with (
            patch("gateway.auth.notebook_jwt.mint_session_jwt", mock_mint),
            patch("gateway.store.notebook_sessions.create_session", mock_ns_create),
            patch(
                "gateway.api.notebook_sessions._get_orchestrator",
                new_callable=AsyncMock,
            ),
            patch("gateway.api.notebook_sessions.is_cloud_mode", return_value=False),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await create_session(
                    body=NotebookSessionCreate(project_id=project.id, branch="main"),
                    store=fake_store,
                )

        assert exc_info.value.status_code == 404
        mock_mint.assert_not_called()
        mock_ns_create.assert_not_called()

        result = await db_session.execute(select(GatewayNotebookSession))
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_create_session_accepts_same_org_project_id(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        """create_session with project owned by org_A and store org_id org_A succeeds.

        Uses the direct-mode env shortcut (SP_NOTEBOOK_DIRECT_URL) to avoid K8s.
        Asserts the returned session has project_id set correctly.
        """
        from gateway.api.notebook_sessions import create_session

        project = _make_project("org_A")
        db_session.add(project)
        await db_session.commit()

        fake_store = _make_fake_store(db_session, org_id="org_A", user_id="user-1")

        monkeypatch.setenv("SP_NOTEBOOK_DIRECT_URL", "http://localhost:2718")

        with (
            patch("gateway.api.notebook_sessions.is_cloud_mode", return_value=False),
            patch(
                "gateway.api.notebook_sessions._get_orchestrator",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_session(
                body=NotebookSessionCreate(project_id=project.id, branch="main"),
                store=fake_store,
            )

        assert result.project_id == project.id

    @pytest.mark.asyncio
    async def test_create_session_with_no_project_id_still_works(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        """create_session with project_id=None bypasses the org precheck entirely.

        Verifies no exception is raised and a session is returned.
        """
        from gateway.api.notebook_sessions import create_session

        fake_store = _make_fake_store(db_session, org_id="org_A", user_id="user-1")

        monkeypatch.setenv("SP_NOTEBOOK_DIRECT_URL", "http://localhost:2718")

        mock_assert = AsyncMock()

        with (
            patch("gateway.api.notebook_sessions.is_cloud_mode", return_value=False),
            patch(
                "gateway.api.notebook_sessions._get_orchestrator",
                new_callable=AsyncMock,
            ),
            patch("gateway.store.github._assert_project_in_org", mock_assert),
        ):
            result = await create_session(
                body=NotebookSessionCreate(project_id=None, branch="main"),
                store=fake_store,
            )

        mock_assert.assert_not_awaited()
        assert result is not None
        assert result.project_id is None
