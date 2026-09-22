"""Eval-run emitter: one ledger row when a run reaches ``running``.

Called from ``store.evals.update_run`` inside the transaction that writes
``status = 'running'`` (runs that fail to start never get here). The
allowance position is the org's eval-run quantity already in the ledger for
the period plus one:

* position <= ``entitlement.included_eval_runs``  -> ``0`` reason ``included``
* otherwise                                       -> ``-50`` reason ``ok``

Payload: ``{"allowance_position": n, "included": allowance, "trigger": ...}``.
Queries inside the run bill separately as governed queries (source ``eval``).

Two runs starting in the same instant can both read the same position; the
monthly reconcile ("the 31st row is the first with -50") catches that drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..ledger import LedgerEntry, unit_quantity
from ..rates import period_of
from ._base import json_safe_payload, metered, never_raises, write_in_savepoint

REASON_OK = "ok"
REASON_INCLUDED = "included"


@never_raises
async def emit_eval_run_credit(
    session: AsyncSession,
    *,
    org_id: str,
    run_id: str,
    trigger: str | None = None,
    user_id: str | None = None,
    entitlement: Any = None,
    now: datetime | None = None,
) -> int | None:
    """Write the eval-run ledger row in ``session``; None when not metered or duplicate."""
    if not org_id or not run_id:
        return None
    pair = await metered(org_id, entitlement)
    if pair is None:
        return None
    resolved, card = pair
    now = now or datetime.now(UTC)
    period = period_of(now)
    position = int(await unit_quantity(session, org_id, period, "eval_run")) + 1
    included = int(resolved.included_eval_runs or 0)
    if position <= included:
        credits, reason = 0, REASON_INCLUDED
    else:
        credits, reason = -card.eval_run_credits, REASON_OK
    entry = LedgerEntry(
        org_id=org_id,
        entry_type="consume",
        credits=credits,
        unit="eval_run",
        quantity=1,
        reason=reason,
        source="eval",
        idempotency_key=f"eval_run:{run_id}",
        occurred_at=now,
        billing_period=period,
        ref_type="eval_run",
        ref_id=run_id,
        user_id=user_id,
        payload=json_safe_payload({"allowance_position": position, "included": included, "trigger": trigger}),
    )
    return await write_in_savepoint(session, entry)


__all__ = ["emit_eval_run_credit"]
