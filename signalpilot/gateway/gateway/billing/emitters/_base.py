"""Shared plumbing for the credit emitters.

Every emitter follows the same contract:

1. It is a no-op returning None when the org's entitlement is not metered
   (local mode, tier ``unlimited``).
2. It is idempotent: the ledger's unique ``idempotency_key`` makes a replay a
   silent no-op.
3. It never raises into the caller. Billing must never break a query, a chat
   run, or an eval run. Failures are logged with a traceback and swallowed.
4. The ledger row lands in the caller's session so it commits (or rolls back)
   with the domain row it describes. The write runs inside a SAVEPOINT where
   the dialect supports one, so a billing failure cannot poison the caller's
   transaction.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .. import rate_card
from ..entitlements import OrgEntitlement, get_entitlement
from ..ledger import LedgerEntry, write_entry
from ..rate_card import RateCard

logger = logging.getLogger("gateway.billing.emitters")


def never_raises[**P, R](fn: Callable[P, Awaitable[R | None]]) -> Callable[P, Awaitable[R | None]]:
    """Wrap an emitter so any exception is logged and turned into None."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return await fn(*args, **kwargs)
        except Exception:
            logger.warning("credit emitter %s failed; billing row skipped", fn.__name__, exc_info=True)
            return None

    return wrapper


async def metered_entitlement(org_id: str, entitlement: OrgEntitlement | None = None) -> OrgEntitlement | None:
    """Return the entitlement to bill against, or None when the org is not metered."""
    resolved = entitlement if entitlement is not None else await get_entitlement(org_id)
    if not resolved.is_metered:
        logger.debug("credit emitter skipped: org %s is not metered (tier %s)", org_id, resolved.tier)
        return None
    return resolved


async def metered(org_id: str, entitlement: OrgEntitlement | None = None) -> tuple[OrgEntitlement, RateCard] | None:
    """The (entitlement, rate card) pair an emitter prices with, or None when
    the org is not metered or no rate card is available (logged by
    ``rate_card.require``; nothing is written rather than something guessed)."""
    resolved = await metered_entitlement(org_id, entitlement)
    if resolved is None:
        return None
    card = await rate_card.require()
    if card is None:
        return None
    return resolved, card


async def write_in_savepoint(session: AsyncSession, entry: LedgerEntry) -> int | None:
    """Write ``entry`` in the caller's transaction, isolated by a SAVEPOINT when possible.

    SQLite (the unit-test dialect) does not reliably support nested
    transactions through the async driver, so the write goes straight into the
    outer transaction there. Postgres gets the savepoint, which keeps the
    caller's transaction usable after a billing-side failure.
    """
    if session.get_bind().dialect.name == "sqlite":
        new_id = await write_entry(session, entry)
    else:
        async with session.begin_nested():
            new_id = await write_entry(session, entry)
    if new_id is not None:
        logger.debug(
            "credit ledger row %s: org=%s unit=%s credits=%s reason=%s key=%s",
            new_id,
            entry.org_id,
            entry.unit,
            entry.credits,
            entry.reason,
            entry.idempotency_key,
        )
    return new_id


def json_safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so the JSON payload stays compact and stable."""
    return {key: value for key, value in payload.items() if value is not None}


__all__ = ["json_safe_payload", "logger", "metered_entitlement", "never_raises", "write_in_savepoint"]
