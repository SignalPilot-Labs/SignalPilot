"""Tests for APP-M-6/M-7: branch validation in POST /api/notebook-sessions.

Covers the precheck added to create_session that validates body.branch
before any side effect (org-membership DB roundtrip, session row insert,
JWT mint, or K8s call).
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


# ─── TestNotebookSessionsBranchValidation ────────────────────────────────────


class TestNotebookSessionsBranchValidation:
    @pytest.mark.asyncio
    async def test_create_session_rejects_invalid_branch_metachars(self, db_session: AsyncSession):
        """create_session with a branch containing shell metacharacters raises HTTP 400.

        Verifies that:
        - The exception detail starts with "Error: agent_branch".
        - mint_session_jwt is NOT called.
        - ns.create_session is NOT called.
        - No GatewayNotebookSession rows are written.
        - Rejection happens BEFORE the org-membership check (same-org project present).
        """
        from gateway.api.notebook_sessions import create_session

        # Same-org project is present — proves rejection is not due to project-org check.
        project = _make_project("org_A")
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
                    body=NotebookSessionCreate(project_id=project.id, branch="main; rm -rf /"),
                    store=fake_store,
                )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail.startswith("Error: agent_branch")
        mock_mint.assert_not_called()
        mock_ns_create.assert_not_called()

        result = await db_session.execute(select(GatewayNotebookSession))
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_create_session_rejects_branch_leading_dash(self, db_session: AsyncSession):
        """create_session with a branch name starting with '-' raises HTTP 400.

        The MCP validator explicitly rejects leading '-' to prevent CLI flag injection.
        Verifies the same rejection set as the metachars test.
        """
        from gateway.api.notebook_sessions import create_session

        # Same-org project present — proves rejection is before project-org check.
        project = _make_project("org_A")
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
                    body=NotebookSessionCreate(project_id=project.id, branch="-delete"),
                    store=fake_store,
                )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail.startswith("Error: agent_branch")
        mock_mint.assert_not_called()
        mock_ns_create.assert_not_called()

        result = await db_session.execute(select(GatewayNotebookSession))
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_create_session_accepts_valid_branch(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        """create_session with a branch using all allowed chars succeeds.

        branch="feature/agent.test-1" exercises letters, digit, '/', '.', '-'.
        Uses SP_NOTEBOOK_DIRECT_URL to bypass K8s. Asserts result.branch matches.
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
                body=NotebookSessionCreate(project_id=project.id, branch="feature/agent.test-1"),
                store=fake_store,
            )

        assert result.branch == "feature/agent.test-1"

    @pytest.mark.asyncio
    async def test_create_session_accepts_default_branch_main(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        """create_session with no explicit branch (defaults to 'main') succeeds.

        Confirms the default branch value still flows through without exception.
        """
        from gateway.api.notebook_sessions import create_session

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
                body=NotebookSessionCreate(),
                store=fake_store,
            )

        assert result.branch == "main"
