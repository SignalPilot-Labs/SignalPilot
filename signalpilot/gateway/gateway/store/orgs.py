"""The ``gateway_orgs`` row every cloud org needs before BYOK and org settings work.

The old plan-tier loader created this row as a side effect of resolving the
tier. The tier now comes from ``gateway.billing.entitlements``; this module
keeps the side effect on its own, called from the plan gate and the limit
resolver. It remembers which orgs it has already ensured so the check costs
one query per org per process, not one per request.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

_ensured: set[str] = set()
_MAX_REMEMBERED = 10_000


async def ensure_gateway_org(org_id: str | None) -> None:
    """Create the ``gateway_orgs`` row for ``org_id`` when it does not exist.

    Never raises: a failure here must not block the request that triggered it.
    Local mode (``org_id`` empty or ``"local"``) needs no row.
    """
    if not org_id or org_id == "local" or org_id in _ensured:
        return
    try:
        from ..db.engine import get_session_factory
        from ..db.models import GatewayOrg

        factory = get_session_factory()
        async with factory() as session:
            existing = await session.scalar(select(GatewayOrg.org_id).where(GatewayOrg.org_id == org_id))
            if existing is None:
                session.add(GatewayOrg(org_id=org_id, byok_enabled=False, created_at=time.time()))
                try:
                    await session.commit()
                    logger.info("Auto-created gateway_orgs row for %s", org_id)
                except IntegrityError:
                    await session.rollback()  # concurrent request won the race
    except Exception:
        logger.warning("Could not ensure gateway_orgs row for %s", org_id, exc_info=True)
        return
    if len(_ensured) >= _MAX_REMEMBERED:
        _ensured.clear()
    _ensured.add(org_id)


def forget_ensured_orgs() -> None:
    """Test hook: drop the per-process memory of ensured orgs."""
    _ensured.clear()


__all__ = ["ensure_gateway_org", "forget_ensured_orgs"]
