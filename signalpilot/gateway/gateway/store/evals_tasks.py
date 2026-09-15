"""Eval run task rows and sandbox attribution (gateway.store.evals split: tasks)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayEvalRun, GatewayEvalRunTask

_TASK_FIELDS = (
    "task_id",
    "position",
    "title",
    "kind",
    "task_class",
    "gt",
    "checks",
    "grade",
    "covers",
    "builds",
    "capture_spec",
    "status",
    "verdict",
    "check_results",
    "answer",
    "duration_s",
    "started_at",
    "finished_at",
    "sandbox",
    "branch_name",
    "capture_result",
    "observed_tables",
    "error",
)


def task_dict(row: GatewayEvalRunTask) -> dict[str, Any]:
    out = {f: getattr(row, f) for f in _TASK_FIELDS}
    out["id"] = row.task_id  # public id is the manifest task id
    out["checks"] = list(row.checks or [])
    out["check_results"] = list(row.check_results or [])
    out["covers"] = list(row.covers or [])
    out["builds"] = list(row.builds or [])
    return out


async def seed_tasks(session: AsyncSession, *, org_id: str, run_id: str, tasks: list[dict[str, Any]]) -> None:
    """Insert the run's task rows in manifest order, all pending."""
    for pos, t in enumerate(tasks):
        session.add(
            GatewayEvalRunTask(
                run_id=run_id,
                org_id=org_id,
                task_id=t["task_id"],
                position=pos,
                title=t.get("title", ""),
                kind=t.get("kind", "query"),
                task_class=t.get("task_class", "read"),
                gt=t.get("gt", ""),
                checks=t.get("checks") or [],
                grade=t.get("grade"),
                covers=t.get("covers") or [],
                builds=t.get("builds") or [],
                capture_spec=t.get("capture_spec"),
            )
        )
    await session.commit()


async def update_task(session: AsyncSession, *, org_id: str, run_id: str, task_id: str, **fields: Any) -> None:
    if not fields:
        return
    await session.execute(
        update(GatewayEvalRunTask)
        .where(
            GatewayEvalRunTask.org_id == org_id,
            GatewayEvalRunTask.run_id == run_id,
            GatewayEvalRunTask.task_id == task_id,
        )
        .values(**fields)
    )
    await session.commit()


async def cancel_open_tasks(session: AsyncSession, *, org_id: str, run_id: str, finished_at: str) -> None:
    """Mark every task that did not finish as cancelled."""
    await session.execute(
        update(GatewayEvalRunTask)
        .where(
            GatewayEvalRunTask.org_id == org_id,
            GatewayEvalRunTask.run_id == run_id,
            GatewayEvalRunTask.status.in_(("pending", "running")),
        )
        .values(
            status="cancelled",
            verdict="CANCELLED",
            answer="Run cancelled by user.",
            error=None,
            finished_at=finished_at,
            sandbox=None,
        )
    )
    await session.commit()


async def get_tasks(session: AsyncSession, *, org_id: str, run_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(GatewayEvalRunTask)
                .where(
                    GatewayEvalRunTask.org_id == org_id,
                    GatewayEvalRunTask.run_id == run_id,
                )
                .order_by(GatewayEvalRunTask.position)
            )
        )
        .scalars()
        .all()
    )
    return [task_dict(t) for t in rows]


async def tasks_with_live_sandboxes(
    session: AsyncSession, *, org_id: str, limit_runs: int = 25
) -> dict[str, dict[str, Any]]:
    """sandbox name -> task marker, for the dashboard's ownership join."""
    run_ids = (
        (
            await session.execute(
                select(GatewayEvalRun.id)
                .where(GatewayEvalRun.org_id == org_id)
                .order_by(GatewayEvalRun.created_at.desc())
                .limit(limit_runs)
            )
        )
        .scalars()
        .all()
    )
    if not run_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(GatewayEvalRunTask).where(
                    GatewayEvalRunTask.org_id == org_id,
                    GatewayEvalRunTask.run_id.in_(run_ids),
                    GatewayEvalRunTask.sandbox.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    index: dict[str, dict[str, Any]] = {}
    for t in rows:
        sandbox = t.sandbox or {}
        name = str(sandbox.get("name", "") or "")
        if name:
            index[name] = {
                "run_id": t.run_id,
                "task_id": t.task_id,
                "task_title": t.title,
            }
    return index


async def live_vercel_sandboxes(session: AsyncSession, *, org_id: str, limit_runs: int = 25) -> list[dict[str, Any]]:
    """Vercel sandboxes attributed to tasks still executing, for the panel.

    The Vercel provider has no pod/label API surface to enumerate, so run
    state is the only inventory: a sandbox is "live" while its task row is
    pending/running (the backend destroys the VM in a finally either way).
    """
    run_ids = (
        (
            await session.execute(
                select(GatewayEvalRun.id)
                .where(GatewayEvalRun.org_id == org_id)
                .order_by(GatewayEvalRun.created_at.desc())
                .limit(limit_runs)
            )
        )
        .scalars()
        .all()
    )
    if not run_ids:
        return []
    rows = (
        (
            await session.execute(
                select(GatewayEvalRunTask).where(
                    GatewayEvalRunTask.org_id == org_id,
                    GatewayEvalRunTask.run_id.in_(run_ids),
                    GatewayEvalRunTask.status.in_(("pending", "running")),
                    GatewayEvalRunTask.sandbox.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    out: list[dict[str, Any]] = []
    for t in rows:
        sandbox = t.sandbox or {}
        if str(sandbox.get("backend", "") or "") != "vercel":
            continue
        name = str(sandbox.get("name", "") or "")
        if not name:
            continue
        out.append(
            {
                "name": name,
                "run_id": t.run_id,
                "task_id": t.task_id,
                "task_title": t.title,
                "task_phase": str(sandbox.get("phase", "") or "agent"),
                "started_at": sandbox.get("started_at"),
            }
        )
    return out
