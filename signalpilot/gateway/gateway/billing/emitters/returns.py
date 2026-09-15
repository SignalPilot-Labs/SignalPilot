"""Thread returns: put a billed thread's credits back.

``return_thread(session, run_id, reason)`` finds the run's ``thread`` row
(idempotency key ``thread:{run_id}``) and, when it consumed credits, writes a
``return`` row of the same magnitude with ``reverses`` pointing at it and
idempotency key ``return:{original_id}``. A thread that was never billed
(reason failed / zero_queries / ...) returns None and writes nothing.

The return lands in the period it is written in (``occurred_at = now``), so a
flag raised after a period closed shows on the current statement, exactly as
the tracking plan specifies.

Reasons: ``flagged_wrong`` (answer flagged within 7 days),
``precision_guarantee`` (Managed month-end job), ``manual`` (staff).

There is no message-feedback route in the gateway today; the function is
exposed for the feedback capture path to call when it lands.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ledger import LedgerEntry
from ..models import GatewayCreditLedger
from ._base import json_safe_payload, metered_entitlement, never_raises, write_in_savepoint

REASON_FLAGGED_WRONG = "flagged_wrong"
REASON_PRECISION = "precision_guarantee"
REASON_MANUAL = "manual"
RETURN_REASONS: frozenset[str] = frozenset({REASON_FLAGGED_WRONG, REASON_PRECISION, REASON_MANUAL})


async def thread_row(session: AsyncSession, run_id: str) -> GatewayCreditLedger | None:
    stmt = select(GatewayCreditLedger).where(GatewayCreditLedger.idempotency_key == f"thread:{run_id}")
    return (await session.execute(stmt)).scalar_one_or_none()


@never_raises
async def return_thread(
    session: AsyncSession,
    run_id: str,
    reason: str = REASON_FLAGGED_WRONG,
    *,
    memo: str | None = None,
    user_id: str | None = None,
    entitlement: Any = None,
    now: datetime | None = None,
) -> int | None:
    """Reverse the thread row of ``run_id``; None when it was not billed or already returned."""
    if reason not in RETURN_REASONS:
        raise ValueError(f"invalid return reason {reason!r}")
    original = await thread_row(session, run_id)
    if original is None or original.entry_type != "consume" or original.credits >= 0:
        return None
    if await metered_entitlement(original.org_id, entitlement) is None:
        return None
    entry = LedgerEntry(
        org_id=original.org_id,
        entry_type="return",
        credits=-original.credits,
        unit="thread",
        quantity=1,
        reason=reason,
        source=original.source,
        idempotency_key=f"return:{original.id}",
        occurred_at=now or datetime.now(UTC),
        ref_type=original.ref_type,
        ref_id=original.ref_id,
        user_id=user_id or original.user_id,
        payload=json_safe_payload({"run_id": run_id, "memo": memo, "original_reason": original.reason}),
        reverses=original.id,
    )
    return await write_in_savepoint(session, entry)


__all__ = ["REASON_FLAGGED_WRONG", "REASON_MANUAL", "REASON_PRECISION", "RETURN_REASONS", "return_thread", "thread_row"]
