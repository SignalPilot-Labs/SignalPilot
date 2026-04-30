"""
Per-session budget ledger — Feature #11 from the feature table.

Tracks USD spending per session/agent. The gateway hard-stops when the budget is hit.
Scoped per-org via the governance contextvar; two orgs cannot see each other's sessions.

DB-backed: all budget state persists in gateway_session_budgets. An in-memory LRU
cache (5s TTL) avoids a DB round-trip on every charge() hot path.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock

from sqlalchemy import select, update

from .context import require_org_id

logger = logging.getLogger(__name__)


@dataclass
class SessionBudget:
    """Tracks spending for a single session."""

    session_id: str
    budget_usd: float
    spent_usd: float = 0.0
    query_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    closed: bool = False

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)

    @property
    def is_exhausted(self) -> bool:
        return self.spent_usd >= self.budget_usd

    def charge(self, amount_usd: float) -> bool:
        """Charge an amount to this budget. Returns False if over budget."""
        if self.spent_usd + amount_usd > self.budget_usd:
            return False
        self.spent_usd += amount_usd
        self.query_count += 1
        self.last_activity = time.time()
        return True

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "budget_usd": self.budget_usd,
            "spent_usd": round(self.spent_usd, 6),
            "remaining_usd": round(self.remaining_usd, 6),
            "query_count": self.query_count,
            "is_exhausted": self.is_exhausted,
        }


class _CacheEntry:
    """LRU cache entry with TTL."""

    __slots__ = ("budget", "expires_at")

    def __init__(self, budget: SessionBudget, ttl: float = 5.0):
        self.budget = budget
        self.expires_at = time.time() + ttl

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


class BudgetLedger:
    """Global ledger managing all session budgets, scoped per-org via contextvar.

    DB-backed with in-memory LRU cache (5s TTL) for the charge() hot path.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = Lock()

    def _get_cached(self, org_id: str, session_id: str) -> SessionBudget | None:
        """Return cached budget if not expired."""
        key = (org_id, session_id)
        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.expired:
                return entry.budget
            if entry and entry.expired:
                del self._cache[key]
        return None

    def _set_cached(self, org_id: str, session_id: str, budget: SessionBudget) -> None:
        with self._lock:
            self._cache[(org_id, session_id)] = _CacheEntry(budget)

    def _invalidate(self, org_id: str, session_id: str) -> None:
        with self._lock:
            self._cache.pop((org_id, session_id), None)

    async def create_session(self, session_id: str, budget_usd: float) -> SessionBudget:
        from ..db.engine import get_session_factory
        from ..db.models import GatewaySessionBudget

        org_id = require_org_id()

        factory = get_session_factory()
        async with factory() as session:
            # Check if already exists
            result = await session.execute(
                select(GatewaySessionBudget).where(
                    GatewaySessionBudget.org_id == org_id,
                    GatewaySessionBudget.session_id == session_id,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                budget = SessionBudget(
                    session_id=existing.session_id,
                    budget_usd=existing.budget_usd,
                    spent_usd=existing.spent_usd,
                    query_count=existing.query_count,
                    created_at=existing.created_at,
                    last_activity=existing.last_activity,
                    closed=existing.closed,
                )
                self._set_cached(org_id, session_id, budget)
                return budget

            now = time.time()
            row = GatewaySessionBudget(
                id=str(uuid.uuid4()),
                org_id=org_id,
                session_id=session_id,
                budget_usd=budget_usd,
                spent_usd=0.0,
                query_count=0,
                created_at=now,
                last_activity=now,
                closed=False,
            )
            session.add(row)
            await session.commit()

        budget = SessionBudget(
            session_id=session_id,
            budget_usd=budget_usd,
            created_at=now,
            last_activity=now,
        )
        self._set_cached(org_id, session_id, budget)
        return budget

    async def get_session(self, session_id: str) -> SessionBudget | None:
        org_id = require_org_id()

        # Check cache first
        cached = self._get_cached(org_id, session_id)
        if cached is not None:
            return cached

        from ..db.engine import get_session_factory
        from ..db.models import GatewaySessionBudget

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(GatewaySessionBudget).where(
                    GatewaySessionBudget.org_id == org_id,
                    GatewaySessionBudget.session_id == session_id,
                )
            )
            row = result.scalar_one_or_none()

        if row is None:
            return None

        budget = SessionBudget(
            session_id=row.session_id,
            budget_usd=row.budget_usd,
            spent_usd=row.spent_usd,
            query_count=row.query_count,
            created_at=row.created_at,
            last_activity=row.last_activity,
            closed=row.closed,
        )
        self._set_cached(org_id, session_id, budget)
        return budget

    async def charge(self, session_id: str, amount_usd: float) -> bool:
        """Charge an amount to a session. Returns False if over budget.

        Uses an atomic UPDATE with a WHERE guard to prevent overspend across pods.
        """
        org_id = require_org_id()

        # Quick check: if no session tracked, allow (no budget = unlimited)
        from ..db.engine import get_session_factory
        from ..db.models import GatewaySessionBudget

        factory = get_session_factory()
        async with factory() as session:
            # Atomic check-and-update: only succeeds if spent + amount <= budget
            result = await session.execute(
                update(GatewaySessionBudget)
                .where(
                    GatewaySessionBudget.org_id == org_id,
                    GatewaySessionBudget.session_id == session_id,
                    GatewaySessionBudget.closed == False,  # noqa: E712
                    GatewaySessionBudget.spent_usd + amount_usd <= GatewaySessionBudget.budget_usd,
                )
                .values(
                    spent_usd=GatewaySessionBudget.spent_usd + amount_usd,
                    query_count=GatewaySessionBudget.query_count + 1,
                    last_activity=time.time(),
                )
            )
            await session.commit()

            if result.rowcount == 0:
                # Either session doesn't exist (no budget = allow) or budget exhausted
                check = await session.execute(
                    select(GatewaySessionBudget).where(
                        GatewaySessionBudget.org_id == org_id,
                        GatewaySessionBudget.session_id == session_id,
                    )
                )
                row = check.scalar_one_or_none()
                if row is None:
                    return True  # No budget tracking for this session
                # Budget exhausted or session closed
                self._invalidate(org_id, session_id)
                return False

        # Invalidate cache so next read picks up new values
        self._invalidate(org_id, session_id)
        return True

    async def get_remaining(self, session_id: str) -> float | None:
        """Get remaining budget for a session. None if no session found."""
        budget = await self.get_session(session_id)
        return budget.remaining_usd if budget else None

    async def close_session(self, session_id: str) -> SessionBudget | None:
        org_id = require_org_id()

        from ..db.engine import get_session_factory
        from ..db.models import GatewaySessionBudget

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(GatewaySessionBudget).where(
                    GatewaySessionBudget.org_id == org_id,
                    GatewaySessionBudget.session_id == session_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None

            await session.execute(
                update(GatewaySessionBudget)
                .where(
                    GatewaySessionBudget.org_id == org_id,
                    GatewaySessionBudget.session_id == session_id,
                )
                .values(closed=True)
            )
            await session.commit()

        self._invalidate(org_id, session_id)
        return SessionBudget(
            session_id=row.session_id,
            budget_usd=row.budget_usd,
            spent_usd=row.spent_usd,
            query_count=row.query_count,
            created_at=row.created_at,
            last_activity=row.last_activity,
            closed=True,
        )

    async def get_all_sessions(self) -> list[dict]:
        """Return all active (non-closed) sessions for the current org."""
        org_id = require_org_id()

        from ..db.engine import get_session_factory
        from ..db.models import GatewaySessionBudget

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(GatewaySessionBudget).where(
                    GatewaySessionBudget.org_id == org_id,
                    GatewaySessionBudget.closed == False,  # noqa: E712
                )
            )
            rows = result.scalars().all()

        return [
            SessionBudget(
                session_id=r.session_id,
                budget_usd=r.budget_usd,
                spent_usd=r.spent_usd,
                query_count=r.query_count,
                created_at=r.created_at,
                last_activity=r.last_activity,
            ).to_dict()
            for r in rows
        ]

    async def total_spent(self) -> float:
        """Return total USD spent across all sessions for the current org."""
        org_id = require_org_id()

        from sqlalchemy import func

        from ..db.engine import get_session_factory
        from ..db.models import GatewaySessionBudget

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(func.coalesce(func.sum(GatewaySessionBudget.spent_usd), 0.0)).where(
                    GatewaySessionBudget.org_id == org_id,
                )
            )
            return float(result.scalar())


# Global ledger singleton
budget_ledger = BudgetLedger()
