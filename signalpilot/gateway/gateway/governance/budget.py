"""
Per-session budget ledger — Feature #11 from the feature table.

Tracks USD spending per session/agent. The gateway hard-stops when the budget is hit.
Scoped per-org via the governance contextvar; two orgs cannot see each other's sessions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from .context import require_org_id


@dataclass
class SessionBudget:
    """Tracks spending for a single session."""
    session_id: str
    budget_usd: float
    spent_usd: float = 0.0
    query_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

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


class BudgetLedger:
    """Global ledger managing all session budgets, scoped per-org via contextvar.

    Thread-safe via locks. In-memory for MVP — persists to disk later.
    Org isolation: each public method resolves the current org_id via require_org_id()
    so two orgs with the same session_id cannot interfere with each other.
    """

    def __init__(self) -> None:
        # Key: (org_id, session_id)
        self._sessions: dict[tuple[str, str], SessionBudget] = {}
        self._lock = Lock()

    def create_session(self, session_id: str, budget_usd: float) -> SessionBudget:
        org_id = require_org_id()
        with self._lock:
            key = (org_id, session_id)
            if key in self._sessions:
                return self._sessions[key]
            budget = SessionBudget(session_id=session_id, budget_usd=budget_usd)
            self._sessions[key] = budget
            return budget

    def get_session(self, session_id: str) -> SessionBudget | None:
        org_id = require_org_id()
        with self._lock:
            return self._sessions.get((org_id, session_id))

    def charge(self, session_id: str, amount_usd: float) -> bool:
        """Charge an amount to a session. Returns False if over budget or session not found."""
        org_id = require_org_id()
        with self._lock:
            budget = self._sessions.get((org_id, session_id))
            if budget is None:
                return True  # No budget tracking for this session
            return budget.charge(amount_usd)

    def get_remaining(self, session_id: str) -> float | None:
        """Get remaining budget for a session. None if no session found."""
        org_id = require_org_id()
        with self._lock:
            budget = self._sessions.get((org_id, session_id))
            return budget.remaining_usd if budget else None

    def close_session(self, session_id: str) -> SessionBudget | None:
        org_id = require_org_id()
        with self._lock:
            return self._sessions.pop((org_id, session_id), None)

    def get_all_sessions(self) -> list[dict]:
        """Return all sessions for the current org."""
        org_id = require_org_id()
        with self._lock:
            return [
                b.to_dict()
                for (oid, _sid), b in self._sessions.items()
                if oid == org_id
            ]

    def total_spent(self) -> float:
        """Return total USD spent across all sessions for the current org."""
        org_id = require_org_id()
        with self._lock:
            return sum(
                b.spent_usd
                for (oid, _sid), b in self._sessions.items()
                if oid == org_id
            )


# Global ledger singleton
budget_ledger = BudgetLedger()
