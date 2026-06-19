from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase
from gateway.models.analysis_trails import AnalysisTrailUpdate, AnalysisTrailUpsert
from gateway.store.analysis_trails import resolve_trail, update_trail, upsert_trail


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_trail_upsert_update_and_resolve(db_session) -> None:
    created = await upsert_trail(
        db_session,
        org_id="org-a",
        trail=AnalysisTrailUpsert(
            source="slack",
            request_id="slack-req-1",
            thread_id="session-slack-req-1",
            runtime_session_id="runtime-1",
            project_id="project-1",
            branch="analysis/slack/slack-req-1-revenue",
            default_branch="main",
            notebook_path="notebooks/slack/revenue.py",
            source_url="https://slack.test/archives/C1/p10",
            source_thread_id="T1:C1:1.0",
            source_request_id="Ev1",
            analysis_user_id="analysis:slack:slack-req-1",
            metadata={"trail_url": "https://app.test/projects?file=notebooks/slack/revenue.py"},
        ),
    )

    assert created.status == "active"
    assert created.project_id == "project-1"
    assert created.metadata["trail_url"].startswith("https://app.test/")

    updated = await update_trail(
        db_session,
        org_id="org-a",
        source="slack",
        request_id="slack-req-1",
        update=AnalysisTrailUpdate(
            status="done",
            latest_commit_sha="abc123",
            metadata={"confidence": 0.9},
        ),
    )

    assert updated is not None
    assert updated.status == "done"
    assert updated.latest_commit_sha == "abc123"
    assert updated.metadata["trail_url"].startswith("https://app.test/")
    assert updated.metadata["confidence"] == 0.9

    by_thread = await resolve_trail(
        db_session,
        org_id="org-a",
        thread_id="session-slack-req-1",
    )
    by_path = await resolve_trail(
        db_session,
        org_id="org-a",
        notebook_path="notebooks/slack/revenue.py",
    )
    cross_org = await resolve_trail(
        db_session,
        org_id="org-b",
        thread_id="session-slack-req-1",
    )

    assert by_thread is not None
    assert by_thread.id == created.id
    assert by_path is not None
    assert by_path.id == created.id
    assert cross_org is None
