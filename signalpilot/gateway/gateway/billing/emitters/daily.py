"""Daily snapshot emitter: covered models and seats beyond allowance.

Runs once per UTC day for every org with a metered, billable entitlement
and writes two rows, idempotent by key:

``model_day:{org_id}:{YYYY-MM-DD}``  unit ``model_day``
``seat_day:{org_id}:{YYYY-MM-DD}``   unit ``seat_day``

Credits on each row = ``-daily_credit_share(billable x monthly rate, day)``
(``rates.daily_credit_share`` carries the rounding remainder so a month sums
exactly). ``quantity`` = the billable count. Reason ``ok`` when billable > 0,
``included`` when the allowance covers everything; a zero row is still
written so every day has a provable snapshot.

What "covered model" reads
--------------------------
``gateway_eval_runs.coverage`` for the org's runs with status ``completed``.
That JSON is produced by ``evals.coverage.compute_coverage`` at the end of a
run: ``coverage.models`` lists every model of the eval set's project (from
the manifest shipped with the run) with ``covered`` = declared by a task's
``covers``/``builds`` or observed in the run's audit trail. Eval runs always
build against the eval set's project repo at its production ref, so the
model universe is the production branch as of the latest completed run.

covered(org) = union over completed runs of {model.name | model.covered},
               intersected with the model set of the latest completed run
               of the same ``project_repo`` (deleted models drop out),
               distinct by lower-cased name across the org's projects.

billable models = max(0, |covered| - included_models).

Seats
-----
``clerk_members.org_member_count`` (accepted memberships at snapshot time).
billable seats = max(0, members - included_seats); the rate is
``rates.seat_month_credits(tier)``. When the count is unavailable the seat
row is skipped and logged; the next run fills it in (same key).

Org enumeration
---------------
Cloud mode: ``SELECT org_id FROM subscriptions`` (the backend-owned row the
entitlement reader already depends on). If that table is unavailable, the
distinct org ids of ``gateway_eval_runs`` and ``gateway_projects``. Each org
is then filtered by ``get_entitlement`` -> ``is_metered and is_billable``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..entitlements import OrgEntitlement, get_entitlement, is_cloud_mode
from ..ledger import LedgerEntry, has_entry
from ..rates import MODEL_MONTH_CREDITS, daily_credit_share, seat_month_credits
from ._base import json_safe_payload, write_in_savepoint
from .clerk_members import org_member_count

logger = logging.getLogger(__name__)

REASON_OK = "ok"
REASON_INCLUDED = "included"

MemberCounter = Callable[[str], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class CoveredModels:
    names: tuple[str, ...] = ()
    runs_read: int = 0
    projects: tuple[str, ...] = field(default_factory=tuple)

    @property
    def count(self) -> int:
        return len(self.names)


def model_day_key(org_id: str, day: date) -> str:
    return f"model_day:{org_id}:{day.isoformat()}"


def seat_day_key(org_id: str, day: date) -> str:
    return f"seat_day:{org_id}:{day.isoformat()}"


def covered_from_runs(runs: list[tuple[str, str, dict[str, Any] | None]]) -> CoveredModels:
    """Reduce ``(created_at, project_repo, coverage)`` rows (any order) to the covered set."""
    covered_by_repo: dict[str, set[str]] = {}
    latest_universe: dict[str, tuple[str, set[str]]] = {}
    read = 0
    for created_at, project_repo, coverage in runs:
        models = (coverage or {}).get("models") if isinstance(coverage, dict) else None
        if not isinstance(models, list):
            continue
        read += 1
        repo = str(project_repo or "")
        universe = {str(m.get("name", "")).lower() for m in models if isinstance(m, dict) and m.get("name")}
        covered = {
            str(m.get("name", "")).lower()
            for m in models
            if isinstance(m, dict) and m.get("name") and bool(m.get("covered"))
        }
        covered_by_repo.setdefault(repo, set()).update(covered)
        stamp = str(created_at or "")
        current = latest_universe.get(repo)
        if current is None or stamp >= current[0]:
            latest_universe[repo] = (stamp, universe)
    names: set[str] = set()
    for repo, covered in covered_by_repo.items():
        names.update(covered & latest_universe[repo][1])
    return CoveredModels(names=tuple(sorted(names)), runs_read=read, projects=tuple(sorted(covered_by_repo)))


async def covered_models(session: AsyncSession, org_id: str) -> CoveredModels:
    from gateway.db.models import GatewayEvalRun

    stmt = select(GatewayEvalRun.created_at, GatewayEvalRun.project_repo, GatewayEvalRun.coverage).where(
        GatewayEvalRun.org_id == org_id,
        GatewayEvalRun.status == "completed",
        GatewayEvalRun.coverage.is_not(None),
    )
    rows = [(row[0], row[1], row[2]) for row in (await session.execute(stmt)).all()]
    return covered_from_runs(rows)


async def candidate_org_ids(session: AsyncSession) -> list[str]:
    """Org ids worth checking for a billable entitlement."""
    if is_cloud_mode():
        try:
            rows = (await session.execute(text("SELECT org_id FROM subscriptions"))).all()
            return sorted({str(row[0]) for row in rows if row[0]})
        except Exception:
            await session.rollback()
            logger.warning("subscriptions table unavailable; falling back to gateway tables for org ids")
    from gateway.db.models import GatewayEvalRun, GatewayProject

    ids: set[str] = set()
    for column in (GatewayEvalRun.org_id, GatewayProject.org_id):
        rows = (await session.execute(select(column).distinct())).all()
        ids.update(str(row[0]) for row in rows if row[0])
    return sorted(ids)


async def write_model_day(
    session: AsyncSession, entitlement: OrgEntitlement, day: date, *, covered: CoveredModels
) -> int | None:
    key = model_day_key(entitlement.org_id, day)
    if await has_entry(session, key):
        return None
    billable = max(0, covered.count - int(entitlement.included_models or 0))
    credits = -daily_credit_share(billable * MODEL_MONTH_CREDITS, day)
    entry = LedgerEntry(
        org_id=entitlement.org_id,
        entry_type="consume",
        credits=credits,
        unit="model_day",
        quantity=billable,
        reason=REASON_OK if billable else REASON_INCLUDED,
        source="system",
        idempotency_key=key,
        occurred_at=datetime(day.year, day.month, day.day, tzinfo=UTC),
        ref_type="snapshot_day",
        ref_id=day.isoformat(),
        payload=json_safe_payload(
            {
                "covered_models": list(covered.names),
                "covered_count": covered.count,
                "included": int(entitlement.included_models or 0),
                "billable": billable,
                "allowance_position": covered.count,
                "eval_runs_read": covered.runs_read,
                "projects": list(covered.projects),
                "monthly_rate": MODEL_MONTH_CREDITS,
            }
        ),
    )
    return await write_in_savepoint(session, entry)


async def write_seat_day(session: AsyncSession, entitlement: OrgEntitlement, day: date, *, members: int) -> int | None:
    key = seat_day_key(entitlement.org_id, day)
    if await has_entry(session, key):
        return None
    rate = seat_month_credits(entitlement.tier)
    billable = max(0, members - int(entitlement.included_seats or 0))
    credits = -daily_credit_share(billable * rate, day)
    entry = LedgerEntry(
        org_id=entitlement.org_id,
        entry_type="consume",
        credits=credits,
        unit="seat_day",
        quantity=billable,
        reason=REASON_OK if billable else REASON_INCLUDED,
        source="system",
        idempotency_key=key,
        occurred_at=datetime(day.year, day.month, day.day, tzinfo=UTC),
        ref_type="snapshot_day",
        ref_id=day.isoformat(),
        payload=json_safe_payload(
            {
                "members": members,
                "included": int(entitlement.included_seats or 0),
                "billable": billable,
                "allowance_position": members,
                "monthly_rate": rate,
            }
        ),
    )
    return await write_in_savepoint(session, entry)


async def snapshot_org(
    session: AsyncSession,
    entitlement: OrgEntitlement,
    day: date,
    *,
    member_counter: MemberCounter = org_member_count,
) -> dict[str, int | None]:
    """Write both rows for one org and commit. Returns the ledger ids written."""
    written: dict[str, int | None] = {"model_day": None, "seat_day": None}
    if not (await has_entry(session, model_day_key(entitlement.org_id, day))):
        covered = await covered_models(session, entitlement.org_id)
        written["model_day"] = await write_model_day(session, entitlement, day, covered=covered)
    if not (await has_entry(session, seat_day_key(entitlement.org_id, day))):
        members = await member_counter(entitlement.org_id)
        if members is None:
            logger.warning("seat snapshot skipped for org %s on %s: member count unavailable", entitlement.org_id, day)
        else:
            written["seat_day"] = await write_seat_day(session, entitlement, day, members=members)
    await session.commit()
    return written


async def run_credit_daily_snapshot(
    session_factory: Callable[[], AsyncSession],
    *,
    day: date | None = None,
    member_counter: MemberCounter = org_member_count,
    entitlement_for: Callable[[str], Awaitable[OrgEntitlement]] = get_entitlement,
) -> int:
    """Snapshot every metered, billable org for ``day`` (default: today UTC). Returns rows written."""
    day = day or datetime.now(UTC).date()
    async with session_factory() as session:
        org_ids = await candidate_org_ids(session)
    rows = 0
    for org_id in org_ids:
        try:
            entitlement = await entitlement_for(org_id)
            if not entitlement.is_metered or not entitlement.is_billable:
                continue
            async with session_factory() as session:
                written = await snapshot_org(session, entitlement, day, member_counter=member_counter)
            rows += sum(1 for value in written.values() if value is not None)
        except Exception:
            logger.warning("credit daily snapshot failed for org %s on %s", org_id, day, exc_info=True)
    if rows:
        logger.info("credit daily snapshot %s: wrote %d row(s) across %d org(s)", day, rows, len(org_ids))
    return rows


__all__ = [
    "CoveredModels",
    "candidate_org_ids",
    "covered_from_runs",
    "covered_models",
    "model_day_key",
    "run_credit_daily_snapshot",
    "seat_day_key",
    "snapshot_org",
    "write_model_day",
    "write_seat_day",
]
