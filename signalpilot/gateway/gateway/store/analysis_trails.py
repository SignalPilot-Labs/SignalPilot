"""Store operations for durable external analysis trails."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayAnalysisTrail
from gateway.models.analysis_trails import (
    AnalysisTrailInfo,
    AnalysisTrailUpdate,
    AnalysisTrailUpsert,
)


async def upsert_trail(
    session: AsyncSession,
    *,
    org_id: str,
    trail: AnalysisTrailUpsert,
) -> AnalysisTrailInfo:
    now = time.time()
    row = (
        await session.execute(
            select(GatewayAnalysisTrail).where(
                GatewayAnalysisTrail.org_id == org_id,
                GatewayAnalysisTrail.source == trail.source,
                GatewayAnalysisTrail.request_id == trail.request_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = GatewayAnalysisTrail(
            id=str(uuid.uuid4()),
            org_id=org_id,
            source=trail.source,
            request_id=trail.request_id,
            thread_id=trail.thread_id,
            runtime_session_id=trail.runtime_session_id,
            project_id=trail.project_id,
            branch=trail.branch,
            default_branch=trail.default_branch,
            notebook_path=trail.notebook_path,
            status=trail.status,
            latest_commit_sha=trail.latest_commit_sha,
            source_url=trail.source_url,
            source_thread_id=trail.source_thread_id,
            source_request_id=trail.source_request_id,
            analysis_user_id=trail.analysis_user_id,
            metadata_json=trail.metadata,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.thread_id = trail.thread_id
        row.runtime_session_id = trail.runtime_session_id
        row.project_id = trail.project_id
        row.branch = trail.branch
        row.default_branch = trail.default_branch
        row.notebook_path = trail.notebook_path
        row.status = trail.status
        row.latest_commit_sha = trail.latest_commit_sha or row.latest_commit_sha
        row.source_url = trail.source_url
        row.source_thread_id = trail.source_thread_id
        row.source_request_id = trail.source_request_id
        row.analysis_user_id = trail.analysis_user_id
        if trail.metadata is not None:
            row.metadata_json = trail.metadata
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return _to_info(row)


async def update_trail(
    session: AsyncSession,
    *,
    org_id: str,
    source: str,
    request_id: str,
    update: AnalysisTrailUpdate,
) -> AnalysisTrailInfo | None:
    row = await get_trail_row(
        session,
        org_id=org_id,
        source=source,
        request_id=request_id,
    )
    if row is None:
        return None
    if update.runtime_session_id is not None:
        row.runtime_session_id = update.runtime_session_id
    if update.status is not None:
        row.status = update.status
    if update.latest_commit_sha is not None:
        row.latest_commit_sha = update.latest_commit_sha
    if update.notebook_path is not None:
        row.notebook_path = update.notebook_path
    if update.metadata is not None:
        row.metadata_json = {**(row.metadata_json or {}), **update.metadata}
    row.updated_at = time.time()
    await session.commit()
    await session.refresh(row)
    return _to_info(row)


async def get_trail_row(
    session: AsyncSession,
    *,
    org_id: str,
    source: str,
    request_id: str,
) -> GatewayAnalysisTrail | None:
    return (
        await session.execute(
            select(GatewayAnalysisTrail).where(
                GatewayAnalysisTrail.org_id == org_id,
                GatewayAnalysisTrail.source == source,
                GatewayAnalysisTrail.request_id == request_id,
            )
        )
    ).scalar_one_or_none()


async def get_trail(
    session: AsyncSession,
    *,
    org_id: str,
    source: str,
    request_id: str,
) -> AnalysisTrailInfo | None:
    row = await get_trail_row(
        session,
        org_id=org_id,
        source=source,
        request_id=request_id,
    )
    return _to_info(row) if row else None


async def resolve_trail(
    session: AsyncSession,
    *,
    org_id: str,
    thread_id: str | None = None,
    notebook_path: str | None = None,
) -> AnalysisTrailInfo | None:
    q = select(GatewayAnalysisTrail).where(GatewayAnalysisTrail.org_id == org_id)
    if thread_id:
        q = q.where(GatewayAnalysisTrail.thread_id == thread_id)
    if notebook_path:
        q = q.where(GatewayAnalysisTrail.notebook_path == notebook_path)
    if not thread_id and not notebook_path:
        return None
    q = q.order_by(GatewayAnalysisTrail.updated_at.desc()).limit(1)
    row = (await session.execute(q)).scalar_one_or_none()
    return _to_info(row) if row else None


def _to_info(row: GatewayAnalysisTrail) -> AnalysisTrailInfo:
    return AnalysisTrailInfo(
        id=row.id,
        org_id=row.org_id,
        source=row.source,
        request_id=row.request_id,
        thread_id=row.thread_id,
        runtime_session_id=row.runtime_session_id,
        project_id=row.project_id,
        branch=row.branch,
        default_branch=row.default_branch,
        notebook_path=row.notebook_path,
        status=row.status,
        latest_commit_sha=row.latest_commit_sha,
        source_url=row.source_url,
        source_thread_id=row.source_thread_id,
        source_request_id=row.source_request_id,
        analysis_user_id=row.analysis_user_id,
        metadata=row.metadata_json or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
