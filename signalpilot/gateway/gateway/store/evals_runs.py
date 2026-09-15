"""Eval config and run rows (gateway.store.evals split: runs).

Runs and the per-org config live in Postgres so the harness works across
gateway replicas and survives restarts. Task rows are in ``evals_tasks``;
accuracy history, regressions and retention are in ``evals_accuracy``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayEvalConfig, GatewayEvalRun, GatewayEvalRunTask

from .evals_tasks import task_dict

logger = logging.getLogger(__name__)

_CONFIG_FIELDS = (
    "repo_url",
    "repo_installation_id",
    "repo_id",
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
            "repo_installation_id": None,
            "repo_id": None,
            "model": "sonnet",
            "max_tasks": 0,
            "prompt_preamble": "",
            "connection": "",
            "autorun_on_knowledge_add": False,
            "notify_emails": [],
        }
    return {
        "repo_url": row.repo_url,
        "repo_installation_id": row.repo_installation_id,
        "repo_id": row.repo_id,
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
        update(GatewayEvalRun).where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id).values(**fields)
    )
    if fields.get("status") == "running":
        # Billing: the run has started. One ledger row per run, in this transaction.
        from gateway.billing.emitters.eval_runs import emit_eval_run_credit

        trigger = (
            await session.execute(
                select(GatewayEvalRun.trigger).where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id)
            )
        ).scalar_one_or_none()
        await emit_eval_run_credit(session, org_id=org_id, run_id=run_id, trigger=trigger)
    await session.commit()


async def get_run(session: AsyncSession, *, org_id: str, run_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(GatewayEvalRun).where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id)
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


async def list_runs(session: AsyncSession, *, org_id: str, limit: int = 50) -> list[dict[str, Any]]:
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
        GatewayEvalRun.status.in_(("preparing", "running", "cancelling")),
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
                    GatewayEvalRun.status.in_(("preparing", "running", "cancelling")),
                    (GatewayEvalRun.lease_expires_at.is_(None)) | (GatewayEvalRun.lease_expires_at <= time.time()),
                )
            )
        )
        .scalars()
        .all()
    )
    return [{**run_dict(r), "api_key_id": r.api_key_id} for r in rows]


async def renew_lease(session: AsyncSession, *, org_id: str, run_id: str, ttl_s: float) -> None:
    await session.execute(
        update(GatewayEvalRun)
        .where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id)
        .values(lease_expires_at=time.time() + ttl_s)
    )
    await session.commit()


async def run_exists(session: AsyncSession, *, org_id: str, run_id: str) -> bool:
    row = (
        await session.execute(
            select(GatewayEvalRun.id).where(GatewayEvalRun.org_id == org_id, GatewayEvalRun.id == run_id)
        )
    ).scalar_one_or_none()
    return row is not None


async def org_ids_with_runs(session: AsyncSession) -> list[str]:
    rows = (await session.execute(select(GatewayEvalRun.org_id).group_by(GatewayEvalRun.org_id))).scalars().all()
    return list(rows)


async def count_runs(session: AsyncSession, *, org_id: str) -> int:
    return (
        await session.execute(select(func.count()).select_from(GatewayEvalRun).where(GatewayEvalRun.org_id == org_id))
    ).scalar_one()
