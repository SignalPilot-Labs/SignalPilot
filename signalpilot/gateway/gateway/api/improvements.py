"""Improvement-run API: manual trigger + history listing."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from datetime import UTC, datetime

from ..db.models import GatewayImprovementRun, GatewayWorkspaceProject
from ..improvements.scheduler import et_date_str
from ..security.scope_guard import RequireScope
from .deps import StoreD


def _now() -> datetime:
    return datetime.now(UTC)

router = APIRouter(prefix="/api")


class ImprovementRunInfo(BaseModel):
    id: str
    org_id: str
    project_id: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    status: str
    trigger: str
    started_et_date: str
    detail: dict | None = None


def _info(row: GatewayImprovementRun) -> ImprovementRunInfo:
    return ImprovementRunInfo(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        conversation_id=row.conversation_id,
        run_id=row.run_id,
        status=row.status,
        trigger=row.trigger,
        started_et_date=row.started_et_date,
        detail=row.detail_json,
    )


@router.get(
    "/improvements/runs",
    response_model=list[ImprovementRunInfo],
    dependencies=[RequireScope("read")],
)
async def list_improvement_runs(store: StoreD):
    rows = (
        await store.session.execute(
            select(GatewayImprovementRun)
            .where(GatewayImprovementRun.org_id == store._require_org_id())
            .order_by(GatewayImprovementRun.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return [_info(row) for row in rows]


@router.post(
    "/improvements/run",
    response_model=ImprovementRunInfo,
    status_code=201,
    dependencies=[RequireScope("admin")],
)
async def trigger_improvement_run(store: StoreD, project_id: str | None = None):
    """Manually start an improvement run now (does not consume the nightly slot)."""
    from ..improvements.runner import seed_improvement_run

    org_id = store._require_org_id()
    query = select(GatewayWorkspaceProject).where(
        GatewayWorkspaceProject.org_id == org_id,
        GatewayWorkspaceProject.connection_name.is_not(None),
    )
    if project_id:
        query = query.where(GatewayWorkspaceProject.id == project_id)
    project = (
        await store.session.execute(query.order_by(GatewayWorkspaceProject.updated_at.desc()).limit(1))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="No connected workspace project found")
    record = GatewayImprovementRun(
        org_id=org_id,
        project_id=project.id,
        status="queued",
        trigger="manual",
        # Manual runs are tagged with a unique slot so they never collide
        # with (or consume) the scheduled nightly slot.
        started_et_date=f"manual-{et_date_str(_now())}-{_now().strftime('%H%M%S%f')}",
    )
    store.session.add(record)
    await store.session.flush()
    try:
        conversation_id, run_id = await seed_improvement_run(
            store.session,
            org_id=org_id,
            project=project,
            trigger="manual",
        )
    except Exception as exc:
        record.status = "failed"
        record.detail_json = {"error": str(exc)[:2000]}
        await store.session.commit()
        raise HTTPException(status_code=409, detail=f"Improvement run failed to start: {exc}") from exc
    record.conversation_id = conversation_id
    record.run_id = run_id
    record.status = "seeded"
    await store.session.commit()
    return _info(record)
