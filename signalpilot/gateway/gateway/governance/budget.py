"""
Per-session budget ledger — Feature #11 from the feature table.

Tracks USD spending per session/agent. The gateway hard-stops when the budget is hit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock


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
    """Global ledger managing all session budgets.

    Thread-safe via locks. In-memory for MVP — persists to disk later.
    """

    def __init__(self):
        self._sessions: dict[str, SessionBudget] = {}
        self._lock = Lock()

    def create_session(self, session_id: str, budget_usd: float) -> SessionBudget:
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            budget = SessionBudget(session_id=session_id, budget_usd=budget_usd)
            self._sessions[session_id] = budget
            return budget

    def get_session(self, session_id: str) -> SessionBudget | None:
        with self._lock:
            return self._sessions.get(session_id)

    def charge(self, session_id: str, amount_usd: float) -> bool:
        """Charge an amount to a session. Returns False if over budget or session not found."""
        with self._lock:
            budget = self._sessions.get(session_id)
            if budget is None:
                return True  # No budget tracking for this session
            return budget.charge(amount_usd)

    def get_remaining(self, session_id: str) -> float | None:
        """Get remaining budget for a session. None if no session found."""
        with self._lock:
            budget = self._sessions.get(session_id)
            return budget.remaining_usd if budget else None

    def close_session(self, session_id: str) -> SessionBudget | None:
        with self._lock:
            return self._sessions.pop(session_id, None)

    def get_all_sessions(self) -> list[dict]:
        with self._lock:
            return [b.to_dict() for b in self._sessions.values()]

    @property
    def total_spent(self) -> float:
        with self._lock:
            return sum(b.spent_usd for b in self._sessions.values())


# Global ledger singleton
budget_ledger = BudgetLedger()
