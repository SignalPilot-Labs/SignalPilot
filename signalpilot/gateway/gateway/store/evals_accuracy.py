"""Eval accuracy history, regressions and retention (gateway.store.evals split).

Accuracy history is immutable and never pruned; run artifacts and traces are
subject to the retention windows in ``gateway.store.evals``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayEvalAccuracyHistory,
    GatewayEvalRegression,
    GatewayEvalRun,
    GatewayEvalRunTask,
)

# Accuracy history + regressions.


async def append_accuracy(session: AsyncSession, *, org_id: str, entry: dict[str, Any]) -> None:
    session.add(GatewayEvalAccuracyHistory(org_id=org_id, **entry))
    await session.commit()


async def list_accuracy(session: AsyncSession, *, org_id: str, limit: int = 500) -> list[dict[str, Any]]:
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


async def list_task_performance(session: AsyncSession, *, org_id: str, limit_runs: int = 50) -> list[dict[str, Any]]:
    """Aggregate recent completed task results for the accuracy page."""
    run_ids = list(
        (
            await session.execute(
                select(GatewayEvalRun.id)
                .where(
                    GatewayEvalRun.org_id == org_id,
                    GatewayEvalRun.status.in_(("completed", "failed")),
                )
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
        await session.execute(
            select(GatewayEvalRunTask, GatewayEvalRun.created_at)
            .join(
                GatewayEvalRun,
                (GatewayEvalRun.id == GatewayEvalRunTask.run_id) & (GatewayEvalRun.org_id == GatewayEvalRunTask.org_id),
            )
            .where(
                GatewayEvalRunTask.org_id == org_id,
                GatewayEvalRunTask.run_id.in_(run_ids),
                GatewayEvalRunTask.verdict.is_not(None),
                GatewayEvalRunTask.verdict != "CANCELLED",
            )
            .order_by(GatewayEvalRun.created_at.desc())
        )
    ).all()
    by_task: dict[str, dict[str, Any]] = {}
    for task, _created_at in rows:
        item = by_task.setdefault(
            task.task_id,
            {
                "task_id": task.task_id,
                "title": task.title,
                "kind": task.kind,
                "class": task.task_class,
                "covers": sorted(set(task.covers or []) | set(task.builds or [])),
                "attempts": 0,
                "correct": 0,
                "partial": 0,
                "off": 0,
                "errors": 0,
                "duration_total_s": 0.0,
                "duration_samples": 0,
                "last_verdict": task.verdict,
                "last_run_id": task.run_id,
            },
        )
        item["attempts"] += 1
        verdict = str(task.verdict or "").upper()
        if verdict == "CORRECT":
            item["correct"] += 1
        elif verdict == "PARTIAL":
            item["partial"] += 1
        elif verdict in ("OFF", "UNKNOWN"):
            item["off"] += 1
        elif verdict in ("ERROR", "SETUP_FAILED"):
            item["errors"] += 1
        if task.duration_s is not None:
            item["duration_total_s"] += float(task.duration_s)
            item["duration_samples"] += 1

    result = []
    for item in by_task.values():
        attempts = item.pop("attempts")
        duration_total = item.pop("duration_total_s")
        duration_samples = item.pop("duration_samples")
        result.append(
            {
                **item,
                "attempts": attempts,
                "pass_rate_pct": round(item["correct"] / attempts * 100.0, 1),
                "avg_duration_s": (round(duration_total / duration_samples, 1) if duration_samples else None),
            }
        )
    return sorted(result, key=lambda item: (item["pass_rate_pct"], -item["attempts"], item["task_id"]))


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


async def record_regression(session: AsyncSession, *, org_id: str, entry: dict[str, Any]) -> str:
    row = GatewayEvalRegression(org_id=org_id, **entry)
    session.add(row)
    await session.commit()
    return row.id


async def list_regressions(session: AsyncSession, *, org_id: str, limit: int = 100) -> list[dict[str, Any]]:
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


async def runs_outside_window(session: AsyncSession, *, org_id: str, window: int, flag: str) -> list[str]:
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
                    GatewayEvalRun.status.not_in(("preparing", "running", "cancelling")),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def mark_pruned(session: AsyncSession, *, org_id: str, run_ids: list[str], flag: str) -> None:
    if not run_ids:
        return
    await session.execute(
        update(GatewayEvalRun)
        .where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id.in_(run_ids))
        .values(**{flag: True})
    )
    await session.commit()


async def delete_trace_rows(session: AsyncSession, *, org_id: str, run_ids: list[str]) -> None:
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
