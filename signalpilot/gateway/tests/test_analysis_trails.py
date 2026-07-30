from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayAnalysisTrail, GatewayBase
from gateway.models.analysis_trails import AnalysisTrailUpdate, AnalysisTrailUpsert
from gateway.store.analysis_trails import (
    latest_trail_for_source_thread_prefix,
    resolve_trail,
    update_trail,
    upsert_trail,
)


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


@pytest.mark.asyncio
async def test_analysis_trail_resolve_uses_session_or_file_when_both_present(db_session) -> None:
    created = await upsert_trail(
        db_session,
        org_id="org-a",
        trail=AnalysisTrailUpsert(
            source="slack",
            request_id="slack-req-2",
            thread_id="session-slack-req-2",
            runtime_session_id="runtime-2",
            project_id="project-1",
            branch="analysis/slack/slack-req-2-hello",
            default_branch="main",
            notebook_path="notebooks/slack/hello-f256fe.py",
            source_url="https://slack.test/archives/C1/p20",
        ),
    )

    by_thread_even_with_stale_path = await resolve_trail(
        db_session,
        org_id="org-a",
        thread_id="session-slack-req-2",
        notebook_path="notebooks/slack/stale-path.py",
    )
    by_path_even_with_stale_thread = await resolve_trail(
        db_session,
        org_id="org-a",
        thread_id="session-slack-stale",
        notebook_path="notebooks/slack/hello-f256fe.py",
    )

    assert by_thread_even_with_stale_path is not None
    assert by_thread_even_with_stale_path.id == created.id
    assert by_path_even_with_stale_thread is not None
    assert by_path_even_with_stale_thread.id == created.id


@pytest.mark.asyncio
async def test_latest_trail_for_source_thread_prefix_returns_newest_matching_trail(db_session) -> None:
    older = await upsert_trail(
        db_session,
        org_id="org-a",
        trail=AnalysisTrailUpsert(
            source="slack",
            request_id="slack-older",
            thread_id="session-slack-older",
            runtime_session_id="runtime-older",
            project_id="project-1",
            branch="analysis/slack/older",
            default_branch="main",
            notebook_path="notebooks/slack/older.py",
            source_thread_id="slack:T1:D1:dm-100.0",
        ),
    )
    newer = await upsert_trail(
        db_session,
        org_id="org-a",
        trail=AnalysisTrailUpsert(
            source="slack",
            request_id="slack-newer",
            thread_id="session-slack-newer",
            runtime_session_id="runtime-newer",
            project_id="project-1",
            branch="analysis/slack/newer",
            default_branch="main",
            notebook_path="notebooks/slack/newer.py",
            source_thread_id="slack:T1:D1:dm-200.0",
        ),
    )
    await upsert_trail(
        db_session,
        org_id="org-a",
        trail=AnalysisTrailUpsert(
            source="notion",
            request_id="notion-newer",
            thread_id="session-notion-newer",
            runtime_session_id="runtime-notion-newer",
            project_id="project-1",
            branch="analysis/notion/newer",
            default_branch="main",
            notebook_path="notebooks/notion/newer.py",
            source_thread_id="slack:T1:D1:dm-300.0",
        ),
    )
    await upsert_trail(
        db_session,
        org_id="org-b",
        trail=AnalysisTrailUpsert(
            source="slack",
            request_id="slack-other-org",
            thread_id="session-slack-other-org",
            runtime_session_id="runtime-other-org",
            project_id="project-1",
            branch="analysis/slack/other-org",
            default_branch="main",
            notebook_path="notebooks/slack/other-org.py",
            source_thread_id="slack:T1:D1:dm-400.0",
        ),
    )

    await db_session.execute(
        update(GatewayAnalysisTrail)
        .where(GatewayAnalysisTrail.request_id == "slack-older")
        .values(created_at=100.0)
    )
    await db_session.execute(
        update(GatewayAnalysisTrail)
        .where(GatewayAnalysisTrail.request_id == "slack-newer")
        .values(created_at=200.0)
    )
    await db_session.commit()

    found = await latest_trail_for_source_thread_prefix(
        db_session,
        org_id="org-a",
        source="slack",
        prefix="slack:T1:D1:dm-",
    )
    missing = await latest_trail_for_source_thread_prefix(
        db_session,
        org_id="org-a",
        source="slack",
        prefix="slack:T2:D1:dm-",
    )

    assert found is not None
    assert found.id == newer.id
    assert found.id != older.id
    assert missing is None
