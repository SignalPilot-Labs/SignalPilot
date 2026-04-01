"""Tests for the per-session budget ledger (Feature #11)."""

import pytest

from signalpilot.gateway.gateway.governance.budget import BudgetLedger, SessionBudget


class TestSessionBudget:
    """Tests for the SessionBudget dataclass."""

    def test_initial_state(self):
        budget = SessionBudget(session_id="test", budget_usd=10.0)
        assert budget.remaining_usd == 10.0
        assert budget.spent_usd == 0.0
        assert not budget.is_exhausted
        assert budget.query_count == 0

    def test_charge_success(self):
        budget = SessionBudget(session_id="test", budget_usd=10.0)
        ok = budget.charge(1.0)
        assert ok is True
        assert budget.spent_usd == 1.0
        assert budget.remaining_usd == 9.0
        assert budget.query_count == 1

    def test_charge_over_budget(self):
        budget = SessionBudget(session_id="test", budget_usd=1.0)
        budget.charge(0.5)
        ok = budget.charge(0.6)  # Would exceed budget
        assert ok is False
        assert budget.spent_usd == 0.5  # Unchanged

    def test_charge_exact_budget(self):
        budget = SessionBudget(session_id="test", budget_usd=1.0)
        ok = budget.charge(1.0)
        assert ok is True
        assert budget.is_exhausted

    def test_exhausted_after_multiple_charges(self):
        budget = SessionBudget(session_id="test", budget_usd=0.003)
        budget.charge(0.001)
        budget.charge(0.001)
        budget.charge(0.001)
        assert budget.is_exhausted
        ok = budget.charge(0.001)
        assert ok is False

    def test_to_dict(self):
        budget = SessionBudget(session_id="test", budget_usd=10.0)
        budget.charge(2.5)
        d = budget.to_dict()
        assert d["session_id"] == "test"
        assert d["budget_usd"] == 10.0
        assert d["spent_usd"] == 2.5
        assert d["remaining_usd"] == 7.5
        assert d["query_count"] == 1
        assert d["is_exhausted"] is False


class TestBudgetLedger:
    """Tests for the BudgetLedger."""

    def test_create_session(self):
        ledger = BudgetLedger()
        budget = ledger.create_session("s1", 10.0)
        assert budget.session_id == "s1"
        assert budget.budget_usd == 10.0

    def test_create_session_idempotent(self):
        ledger = BudgetLedger()
        b1 = ledger.create_session("s1", 10.0)
        b2 = ledger.create_session("s1", 20.0)  # Same ID, different budget
        assert b1 is b2  # Returns existing
        assert b1.budget_usd == 10.0  # Original budget unchanged

    def test_get_session(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 10.0)
        assert ledger.get_session("s1") is not None
        assert ledger.get_session("s2") is None

    def test_charge(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 1.0)
        ok = ledger.charge("s1", 0.5)
        assert ok is True
        ok = ledger.charge("s1", 0.6)  # Exceeds
        assert ok is False

    def test_charge_unknown_session(self):
        """Charging an unknown session should succeed (no budget = unlimited)."""
        ledger = BudgetLedger()
        ok = ledger.charge("unknown", 100.0)
        assert ok is True

    def test_get_remaining(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 5.0)
        ledger.charge("s1", 1.5)
        assert ledger.get_remaining("s1") == 3.5
        assert ledger.get_remaining("unknown") is None

    def test_close_session(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 10.0)
        closed = ledger.close_session("s1")
        assert closed is not None
        assert ledger.get_session("s1") is None

    def test_close_nonexistent_session(self):
        ledger = BudgetLedger()
        closed = ledger.close_session("nonexistent")
        assert closed is None

    def test_get_all_sessions(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 10.0)
        ledger.create_session("s2", 20.0)
        sessions = ledger.get_all_sessions()
        assert len(sessions) == 2

    def test_total_spent(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 10.0)
        ledger.create_session("s2", 10.0)
        ledger.charge("s1", 1.5)
        ledger.charge("s2", 2.5)
        assert ledger.total_spent == 4.0
