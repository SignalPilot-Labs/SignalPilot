"""Gateway background loops.

``credit_daily_snapshot_loop`` writes the ``model_day`` / ``seat_day`` credit
rows once per UTC day. It runs the snapshot shortly after startup (so a
restart on a day that was missed still gets its row) and then at
``SNAPSHOT_HOUR_UTC:SNAPSHOT_MINUTE_UTC`` every day. The snapshot itself is
idempotent by ``{unit}:{org}:{date}``, so overlapping instances only cost a
few reads.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

SNAPSHOT_HOUR_UTC = 0
SNAPSHOT_MINUTE_UTC = 5
STARTUP_DELAY_SECONDS = 90.0
MAX_SLEEP_SECONDS = 6 * 60 * 60.0


def seconds_until_next_snapshot(now: datetime | None = None) -> float:
    """Seconds from ``now`` (aware UTC) to the next 00:05 UTC, capped so clock drift is re-checked."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    target = now.replace(hour=SNAPSHOT_HOUR_UTC, minute=SNAPSHOT_MINUTE_UTC, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return min(MAX_SLEEP_SECONDS, max(1.0, (target - now).total_seconds()))


async def credit_daily_snapshot_loop(session_factory, *, startup_delay: float = STARTUP_DELAY_SECONDS) -> None:
    """Run the credit daily snapshot at startup and then once per UTC day, forever."""
    from gateway.billing.emitters.daily import run_credit_daily_snapshot

    await asyncio.sleep(startup_delay)
    while True:
        try:
            await run_credit_daily_snapshot(session_factory)
        except Exception:
            logger.warning("credit daily snapshot loop error", exc_info=True)
        await asyncio.sleep(seconds_until_next_snapshot())


__all__ = ["credit_daily_snapshot_loop", "seconds_until_next_snapshot"]
