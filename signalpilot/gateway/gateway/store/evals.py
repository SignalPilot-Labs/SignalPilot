"""Eval harness state, scoped by org_id.

Runs, tasks, config, accuracy history and regressions live in Postgres so the
harness works across gateway replicas and survives restarts. Bulky evidence
(transcripts, setup logs, table captures) lives in S3 under
``evals/<org>/runs/<run_id>/``. These rows contain only pointers and summaries.

Accuracy history is immutable and never pruned; everything else is subject to
the retention windows (10 runs of artifacts, 100 runs of traces).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayEvalAccuracyHistory,
    GatewayEvalConfig,
    GatewayEvalRegression,
    GatewayEvalRun,
    GatewayEvalRunTask,
)

logger = logging.getLogger(__name__)

# Retention windows (spec §3.5). Artifacts are heavy (table captures); traces
# are the transcripts + run/task rows. History is forever.
ARTIFACT_RUN_WINDOW = 10
TRACE_RUN_WINDOW = 100

_CONFIG_FIELDS = (
    "repo_url",
    "model",
    "max_tasks",
    "prompt_preamble",
    "connection",
    "autorun_on_knowledge_add",
    "notify_emails",
)


def _config_dict(row: GatewayEvalConfig | None) -> dict[str, Any]:
    if row is None:
        return {
            "repo_url": "",
            "model": "sonnet",
            "max_tasks": 0,
            "prompt_preamble": "",
            "connection": "",
            "autorun_on_knowledge_add": False,
            "notify_emails": [],
        }
    return {
        "repo_url": row.repo_url,
        "model": row.model,
        "max_tasks": row.max_tasks,
        "prompt_preamble": row.prompt_preamble,
        "connection": row.connection,
        "autorun_on_knowledge_add": row.autorun_on_knowledge_add,
        "notify_emails": list(row.notify_emails or []),
    }


async def get_config(session: AsyncSession, *, org_id: str) -> dict[str, Any]:
    row = await session.get(GatewayEvalConfig, org_id)
    return _config_dict(row)


async def save_config(session: AsyncSession, *, org_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    row = await session.get(GatewayEvalConfig, org_id)
    if row is None:
        row = GatewayEvalConfig(org_id=org_id)
        session.add(row)
    for field in _CONFIG_FIELDS:
        if field in cfg:
            setattr(row, field, cfg[field])
    row.updated_at = time.time()
    await session.commit()
    return _config_dict(row)


# Runs.

_RUN_LIST_FIELDS = (
    "id",
    "org_id",
    "status",
    "trigger",
    "created_at",
    "finished_at",
    "doc_ids",
    "doc_titles",
    "repo_url",
    "model",
    "eval_set_name",
    "eval_set_ref",
    "project_repo",
    "project_ref",
    "build_fingerprint",
    "kb_doc_ids",
    "summary",
    "progress",
    "coverage",
    "error",
    "artifact_bytes",
    "artifacts_pruned",
    "traces_pruned",
    "config_hash",
)


def run_dict(row: GatewayEvalRun) -> dict[str, Any]:
    out = {f: getattr(row, f) for f in _RUN_LIST_FIELDS}
    out["doc_ids"] = list(row.doc_ids or [])
    out["doc_titles"] = list(row.doc_titles or [])
    out["kb_doc_ids"] = list(row.kb_doc_ids or [])
    out["summary"] = dict(row.summary or {})
    out["progress"] = dict(row.progress or {})
    out["coverage"] = dict(row.coverage or {}) or None
    out["task_filter"] = list(row.task_filter or []) or None
    return out


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


async def create_run(
    session: AsyncSession,
    *,
    org_id: str,
    run_id: str,
    created_at: str,
    trigger: str,
    doc_ids: list[str],
    doc_titles: list[str],
    task_filter: list[str] | None,
    repo_url: str,
    model: str,
) -> dict[str, Any]:
    row = GatewayEvalRun(
        id=run_id,
        org_id=org_id,
        status="preparing",
        trigger=trigger,
        created_at=created_at,
        doc_ids=doc_ids,
        doc_titles=doc_titles,
        task_filter=task_filter,
        repo_url=repo_url,
        model=model,
    )
    session.add(row)
    await session.commit()
    return run_dict(row)


async def update_run(session: AsyncSession, *, org_id: str, run_id: str, **fields: Any) -> None:
    if not fields:
        return
    await session.execute(
        update(GatewayEvalRun)
        .where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id)
        .values(**fields)
    )
    await session.commit()


async def get_run(session: AsyncSession, *, org_id: str, run_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(GatewayEvalRun).where(
                GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    out = run_dict(row)
    tasks = (
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
    out["tasks"] = [task_dict(t) for t in tasks]
    return out


async def list_runs(
    session: AsyncSession, *, org_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(GatewayEvalRun)
                .where(GatewayEvalRun.org_id == org_id)
                .order_by(GatewayEvalRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [run_dict(r) for r in rows]


async def list_live_runs(session: AsyncSession, *, org_id: str | None = None) -> list[dict[str, Any]]:
    """Return runs with a valid lease.

    When org_id is None, return runs from all organizations for the reaper.
    Use the lease instead of status to determine whether a run is active.
    """
    stmt = select(GatewayEvalRun).where(
        GatewayEvalRun.status.in_(("preparing", "running")),
        GatewayEvalRun.lease_expires_at.is_not(None),
        GatewayEvalRun.lease_expires_at > time.time(),
    )
    if org_id is not None:
        stmt = stmt.where(GatewayEvalRun.org_id == org_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [run_dict(r) for r in rows]


async def list_stale_runs(session: AsyncSession) -> list[dict[str, Any]]:
    """Return active-status runs that have an expired lease."""
    rows = (
        (
            await session.execute(
                select(GatewayEvalRun).where(
                    GatewayEvalRun.status.in_(("preparing", "running")),
                    (GatewayEvalRun.lease_expires_at.is_(None))
                    | (GatewayEvalRun.lease_expires_at <= time.time()),
                )
            )
        )
        .scalars()
        .all()
    )
    return [{**run_dict(r), "api_key_id": r.api_key_id} for r in rows]


async def renew_lease(
    session: AsyncSession, *, org_id: str, run_id: str, ttl_s: float
) -> None:
    await session.execute(
        update(GatewayEvalRun)
        .where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id)
        .values(lease_expires_at=time.time() + ttl_s)
    )
    await session.commit()


# Tasks.


async def seed_tasks(
    session: AsyncSession, *, org_id: str, run_id: str, tasks: list[dict[str, Any]]
) -> None:
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


async def update_task(
    session: AsyncSession, *, org_id: str, run_id: str, task_id: str, **fields: Any
) -> None:
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


async def get_tasks(
    session: AsyncSession, *, org_id: str, run_id: str
) -> list[dict[str, Any]]:
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


# Accuracy history + regressions.


async def append_accuracy(
    session: AsyncSession, *, org_id: str, entry: dict[str, Any]
) -> None:
    session.add(GatewayEvalAccuracyHistory(org_id=org_id, **entry))
    await session.commit()


async def list_accuracy(
    session: AsyncSession, *, org_id: str, limit: int = 500
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(GatewayEvalAccuracyHistory)
                .where(GatewayEvalAccuracyHistory.org_id == org_id)
                .order_by(GatewayEvalAccuracyHistory.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "run_id": r.run_id,
            "created_at": r.created_at,
            "trigger": r.trigger,
            "eval_set_name": r.eval_set_name,
            "eval_set_ref": r.eval_set_ref,
            "build_fingerprint": r.build_fingerprint,
            "tasks_total": r.tasks_total,
            "tasks_passed": r.tasks_passed,
            "accuracy_pct": r.accuracy_pct,
            "coverage_pct": r.coverage_pct,
            "kb_doc_ids": list(r.kb_doc_ids or []),
        }
        for r in rows
    ]


async def trailing_baseline(
    session: AsyncSession,
    *,
    org_id: str,
    eval_set_ref: str,
    build_fingerprint: str,
    before: str,
    window: int = 5,
) -> list[dict[str, Any]]:
    """Return comparable runs with the same set reference and build fingerprint."""
    rows = (
        (
            await session.execute(
                select(GatewayEvalAccuracyHistory)
                .where(
                    GatewayEvalAccuracyHistory.org_id == org_id,
                    GatewayEvalAccuracyHistory.eval_set_ref == eval_set_ref,
                    GatewayEvalAccuracyHistory.build_fingerprint == build_fingerprint,
                    GatewayEvalAccuracyHistory.created_at < before,
                )
                .order_by(GatewayEvalAccuracyHistory.created_at.desc())
                .limit(window)
            )
        )
        .scalars()
        .all()
    )
    # The run row carries the config that was in force; the attribution check
    # needs it to tell "the KB changed" from "the model/prompt changed too".
    run_rows = {
        r.id: r
        for r in (
            await session.execute(
                select(GatewayEvalRun).where(
                    GatewayEvalRun.org_id == org_id,
                    GatewayEvalRun.id.in_([x.run_id for x in rows]) if rows else False,
                )
            )
        )
        .scalars()
        .all()
    }
    out = []
    for r in rows:
        run_row = run_rows.get(r.run_id)
        out.append(
            {
                "run_id": r.run_id,
                "accuracy_pct": r.accuracy_pct,
                "kb_doc_ids": list(r.kb_doc_ids or []),
                "meta": {
                    "model": getattr(run_row, "model", None),
                    "config_hash": getattr(run_row, "config_hash", None),
                }
                if run_row is not None
                else {},
            }
        )
    return out


async def record_regression(
    session: AsyncSession, *, org_id: str, entry: dict[str, Any]
) -> str:
    row = GatewayEvalRegression(org_id=org_id, **entry)
    session.add(row)
    await session.commit()
    return row.id


async def list_regressions(
    session: AsyncSession, *, org_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(GatewayEvalRegression)
                .where(GatewayEvalRegression.org_id == org_id)
                .order_by(GatewayEvalRegression.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "run_id": r.run_id,
            "created_at": r.created_at,
            "baseline_run_ids": list(r.baseline_run_ids or []),
            "baseline_accuracy_pct": r.baseline_accuracy_pct,
            "run_accuracy_pct": r.run_accuracy_pct,
            "drop_pct": r.drop_pct,
            "suspected_doc_ids": list(r.suspected_doc_ids or []),
            "sole_change": r.sole_change,
            "flipped_tasks": list(r.flipped_tasks or []),
            "notified_at": r.notified_at,
            "recipients": list(r.recipients or []),
        }
        for r in rows
    ]


# Retention.


async def runs_outside_window(
    session: AsyncSession, *, org_id: str, window: int, flag: str
) -> list[str]:
    """Run ids past the given retention window whose `flag` column is false.

    flag is "artifacts_pruned" or "traces_pruned". Enforced on write at run
    finalization; the sweeper is the backstop.
    """
    col = getattr(GatewayEvalRun, flag)
    keep = (
        select(GatewayEvalRun.id)
        .where(GatewayEvalRun.org_id == org_id)
        .order_by(GatewayEvalRun.created_at.desc())
        .limit(window)
    )
    rows = (
        (
            await session.execute(
                select(GatewayEvalRun.id).where(
                    GatewayEvalRun.org_id == org_id,
                    col.is_(False),
                    GatewayEvalRun.id.not_in(keep),
                    GatewayEvalRun.status.not_in(("preparing", "running")),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def mark_pruned(
    session: AsyncSession, *, org_id: str, run_ids: list[str], flag: str
) -> None:
    if not run_ids:
        return
    await session.execute(
        update(GatewayEvalRun)
        .where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id.in_(run_ids))
        .values(**{flag: True})
    )
    await session.commit()


async def delete_trace_rows(
    session: AsyncSession, *, org_id: str, run_ids: list[str]
) -> None:
    """Drop task detail for runs past the trace window (run row stays as a
    tombstone; the immutable accuracy record is elsewhere)."""
    if not run_ids:
        return
    await session.execute(
        delete(GatewayEvalRunTask).where(
            GatewayEvalRunTask.org_id == org_id,
            GatewayEvalRunTask.run_id.in_(run_ids),
        )
    )
    await session.commit()


async def run_exists(session: AsyncSession, *, org_id: str, run_id: str) -> bool:
    row = (
        await session.execute(
            select(GatewayEvalRun.id).where(
                GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def org_ids_with_runs(session: AsyncSession) -> list[str]:
    rows = (await session.execute(select(GatewayEvalRun.org_id).group_by(GatewayEvalRun.org_id))).scalars().all()
    return list(rows)


async def count_runs(session: AsyncSession, *, org_id: str) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(GatewayEvalRun).where(GatewayEvalRun.org_id == org_id)
        )
    ).scalar_one()
