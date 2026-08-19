"""Daily scheduler for automated improvement runs.

An org with the ``improvement_runs_enabled`` setting gets at most one
system-initiated improvement run per America/New_York calendar day. Per-day
uniqueness is enforced twice: the due-check compares ET calendar dates against
the recorded ``started_et_date``, and the (org_id, started_et_date) unique
constraint on gateway_improvement_runs makes double-fires impossible even
across processes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from gateway.db.models import GatewayImprovementRun, GatewaySetting, GatewayWorkspaceProject

logger = logging.getLogger(__name__)

ET_ZONE = ZoneInfo("America/New_York")


def et_date_str(dt: datetime) -> str:
    """The America/New_York calendar date (YYYY-MM-DD) of a UTC datetime.

    A naive datetime is interpreted as UTC. zoneinfo handles DST, so the
    spring-forward and fall-back days are just calendar days.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ET_ZONE).date().isoformat()


def improvement_run_due(now_utc: datetime, last_run_at_utc: datetime | None) -> bool:
    """True when no improvement run has been started for the current ET day.

    Both arguments are UTC datetimes (naive treated as UTC). Midnight ET has
    always "passed" for the current ET day, so the run is due exactly when the
    last run's ET calendar date differs from today's ET calendar date.
    """
    if last_run_at_utc is None:
        return True
    return et_date_str(last_run_at_utc) != et_date_str(now_utc)


async def run_due_improvement_runs(session_factory, *, now_utc: datetime | None = None) -> int:
    """Seed due improvement runs for every enabled org.

    Returns the number of orgs for which a day slot was consumed (seeded,
    skipped, or failed). One org's failure never breaks the loop.
    """
    now = now_utc or datetime.now(UTC)
    today_et = et_date_str(now)

    async with session_factory() as session:
        rows = (await session.execute(select(GatewaySetting))).scalars().all()
        enabled_org_ids = [
            row.org_id for row in rows if (row.settings_json or {}).get("improvement_runs_enabled") is True
        ]

    processed = 0
    for org_id in enabled_org_ids:
        try:
            if await _run_for_org(session_factory, org_id=org_id, today_et=today_et):
                processed += 1
        except Exception as e:
            logger.warning("Improvement run scheduling failed for org %s: %s", org_id, e)
    return processed


async def _run_for_org(session_factory, *, org_id: str, today_et: str) -> bool:
    """Consume today's slot for one org and seed its run. Returns True when a slot was consumed."""
    async with session_factory() as db:
        existing = (
            await db.execute(
                select(GatewayImprovementRun.id).where(
                    GatewayImprovementRun.org_id == org_id,
                    GatewayImprovementRun.started_et_date == today_et,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False

        project = (
            await db.execute(
                select(GatewayWorkspaceProject)
                .where(
                    GatewayWorkspaceProject.org_id == org_id,
                    GatewayWorkspaceProject.status == "active",
                    GatewayWorkspaceProject.connection_name.is_not(None),
                    GatewayWorkspaceProject.connection_name != "",
                )
                .order_by(GatewayWorkspaceProject.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        record = GatewayImprovementRun(
            id=str(uuid.uuid4()),
            org_id=org_id,
            project_id=project.id if project else None,
            status="queued" if project else "skipped",
            trigger="scheduled",
            detail_json=(None if project else {"reason": "no active project with a connection for this org"}),
            started_et_date=today_et,
        )
        db.add(record)
        try:
            await db.commit()
        except IntegrityError:
            # Another process consumed today's slot between our check and commit.
            await db.rollback()
            return False

        if project is None:
            logger.info("Improvement run skipped for org %s: no eligible project", org_id)
            return True

        try:
            # Imported at call time: the runner module is replaceable (and may
            # not exist in early deployments) without breaking scheduler import.
            from gateway.improvements.runner import seed_improvement_run

            conversation_id, run_id = await seed_improvement_run(
                db, org_id=org_id, project=project, trigger="scheduled"
            )
        except Exception as e:
            logger.warning("Improvement run seeding failed for org %s: %s", org_id, e)
            record.status = "failed"
            record.detail_json = {"error": str(e)[:2000]}
            await db.commit()
            return True

        record.conversation_id = conversation_id
        record.run_id = run_id
        record.status = "seeded"
        await db.commit()
        logger.info("Improvement run seeded for org %s (conversation=%s run=%s)", org_id, conversation_id, run_id)
        return True
