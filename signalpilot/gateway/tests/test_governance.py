"""Tests for the governance layer — budget, cost estimation, PII redaction, caching."""

import pytest

from gateway.governance.budget import BudgetLedger, SessionBudget
from gateway.governance.cache import QueryCache
from gateway.governance.pii import PIIRedactor, PIIRule, _hash_value, _mask_value


class TestSessionBudget:
    """Test individual session budget tracking."""

    def test_budget_creation(self):
        b = SessionBudget(session_id="test-1", budget_usd=10.0)
        assert b.remaining_usd == 10.0
        assert b.spent_usd == 0.0
        assert not b.is_exhausted

    def test_charge_within_budget(self):
        b = SessionBudget(session_id="test-1", budget_usd=10.0)
        assert b.charge(5.0) is True
        assert b.spent_usd == 5.0
        assert b.remaining_usd == 5.0
        assert b.query_count == 1

    def test_charge_over_budget_rejected(self):
        b = SessionBudget(session_id="test-1", budget_usd=10.0)
        b.charge(9.0)
        assert b.charge(2.0) is False  # Would exceed budget
        assert b.spent_usd == 9.0  # Not charged
        assert b.query_count == 1  # Count not incremented

    def test_exact_budget_allowed(self):
        b = SessionBudget(session_id="test-1", budget_usd=10.0)
        assert b.charge(10.0) is True
        assert b.is_exhausted

    def test_exhausted_budget_rejects_any_charge(self):
        b = SessionBudget(session_id="test-1", budget_usd=1.0)
        b.charge(1.0)
        assert b.charge(0.001) is False

    def test_to_dict(self):
        b = SessionBudget(session_id="test-1", budget_usd=10.0)
        b.charge(3.5)
        d = b.to_dict()
        assert d["session_id"] == "test-1"
        assert d["budget_usd"] == 10.0
        assert d["spent_usd"] == 3.5
        assert d["remaining_usd"] == 6.5
        assert d["query_count"] == 1
        assert d["is_exhausted"] is False


class TestBudgetLedger:
    """Test the global budget ledger."""

    def test_create_session(self):
        ledger = BudgetLedger()
        budget = ledger.create_session("sess-1", 25.0)
        assert budget.budget_usd == 25.0
        assert budget.session_id == "sess-1"

    def test_duplicate_session_returns_existing(self):
        ledger = BudgetLedger()
        b1 = ledger.create_session("sess-1", 25.0)
        b1.charge(5.0)
        b2 = ledger.create_session("sess-1", 100.0)
        assert b2.budget_usd == 25.0  # Original budget, not overwritten
        assert b2.spent_usd == 5.0

    def test_charge_session(self):
        ledger = BudgetLedger()
        ledger.create_session("sess-1", 10.0)
        assert ledger.charge("sess-1", 3.0) is True
        assert ledger.get_remaining("sess-1") == 7.0

    def test_charge_unknown_session_allowed(self):
        """No budget tracking = no limit."""
        ledger = BudgetLedger()
        assert ledger.charge("unknown", 999.0) is True

    def test_close_session(self):
        ledger = BudgetLedger()
        ledger.create_session("sess-1", 10.0)
        closed = ledger.close_session("sess-1")
        assert closed is not None
        assert ledger.get_session("sess-1") is None

    def test_total_spent(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 10.0)
        ledger.create_session("s2", 20.0)
        ledger.charge("s1", 3.0)
        ledger.charge("s2", 7.0)
        assert ledger.total_spent == 10.0

    def test_get_all_sessions(self):
        ledger = BudgetLedger()
        ledger.create_session("s1", 10.0)
        ledger.create_session("s2", 20.0)
        sessions = ledger.get_all_sessions()
        assert len(sessions) == 2


class TestPIIMasking:
    """Test PII value masking and hashing."""

    def test_hash_value(self):
        result = _hash_value("test@example.com")
        assert result.startswith("sha256:")
        assert len(result) == 19  # "sha256:" + 12 hex chars

    def test_hash_none(self):
        assert _hash_value(None) == "NULL"

    def test_hash_deterministic(self):
        assert _hash_value("test") == _hash_value("test")

    def test_mask_email(self):
        result = _mask_value("john@example.com")
        assert "@example.com" in result
        assert "john" not in result

    def test_mask_phone(self):
        result = _mask_value("555-123-4567")
        assert result.endswith("4567")
        assert "555" not in result or result.startswith("***")

    def test_mask_short_value(self):
        assert _mask_value("AB") == "***"

    def test_mask_none(self):
        assert _mask_value(None) == "NULL"

    def test_mask_generic(self):
        result = _mask_value("secret-value")
        assert result[0] == "s"
        assert result[-1] == "e"
        assert "***" in result


class TestPIIRedactor:
    """Test PII redaction on query results."""

    def test_no_rules_passthrough(self):
        redactor = PIIRedactor()
        rows = [{"name": "John", "email": "john@test.com"}]
        result = redactor.redact_rows(rows)
        assert result == rows

    def test_hash_rule(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.hash)
        rows = [{"name": "John", "email": "john@test.com"}]
        result = redactor.redact_rows(rows)
        assert result[0]["name"] == "John"
        assert result[0]["email"].startswith("sha256:")
        assert "john@test.com" not in str(result)

    def test_mask_rule(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.mask)
        rows = [{"name": "John", "email": "john@test.com"}]
        result = redactor.redact_rows(rows)
        assert "@test.com" in result[0]["email"]
        assert "john" not in result[0]["email"]

    def test_drop_rule(self):
        redactor = PIIRedactor()
        redactor.add_rule("ssn", PIIRule.drop)
        rows = [{"name": "John", "ssn": "123-45-6789"}]
        result = redactor.redact_rows(rows)
        assert "ssn" not in result[0]
        assert result[0]["name"] == "John"

    def test_multiple_rules(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.hash)
        redactor.add_rule("phone", PIIRule.mask)
        redactor.add_rule("ssn", PIIRule.drop)
        rows = [
            {"name": "John", "email": "j@t.com", "phone": "555-1234", "ssn": "999"},
        ]
        result = redactor.redact_rows(rows)
        assert result[0]["name"] == "John"
        assert result[0]["email"].startswith("sha256:")
        assert "ssn" not in result[0]
        assert "1234" in result[0]["phone"]

    def test_case_insensitive_column_matching(self):
        redactor = PIIRedactor()
        redactor.add_rule("Email", PIIRule.hash)
        rows = [{"email": "test@test.com"}]
        result = redactor.redact_rows(rows)
        assert result[0]["email"].startswith("sha256:")

    def test_last_redacted_columns_tracked(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.hash)
        redactor.add_rule("ssn", PIIRule.drop)
        rows = [{"name": "John", "email": "j@t.com", "ssn": "999"}]
        redactor.redact_rows(rows)
        assert set(redactor.last_redacted_columns) == {"email", "ssn"}

    def test_load_from_annotations(self):
        redactor = PIIRedactor()
        annotations = {
            "tables": {
                "users": {
                    "columns": {
                        "email": {"pii": "hash"},
                        "phone": {"pii": "mask"},
                        "ssn": {"pii": "drop"},
                        "name": {},  # No PII rule
                    }
                }
            }
        }
        redactor.add_rules_from_annotations(annotations)
        assert redactor.rule_count == 3

    def test_empty_rows(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.hash)
        assert redactor.redact_rows([]) == []


class TestQueryCache:
    """Test query result caching and invalidation."""

    def _make_cache(self) -> QueryCache:
        return QueryCache(max_entries=100, ttl_seconds=300)

    def test_put_and_get(self):
        cache = self._make_cache()
        cache.put("conn1", "SELECT 1", 100, [{"a": 1}], ["t"], 5.0, "SELECT 1")
        entry = cache.get("conn1", "SELECT 1", 100)
        assert entry is not None
        assert entry.rows == [{"a": 1}]

    def test_miss_returns_none(self):
        cache = self._make_cache()
        assert cache.get("conn1", "SELECT 1", 100) is None

    def test_invalidate_all(self):
        cache = self._make_cache()
        cache.put("conn1", "SELECT 1", 100, [], [], 1.0, "SELECT 1")
        cache.put("conn2", "SELECT 2", 100, [], [], 1.0, "SELECT 2")
        count = cache.invalidate()
        assert count == 2
        assert cache.get("conn1", "SELECT 1", 100) is None
        assert cache.get("conn2", "SELECT 2", 100) is None

    def test_invalidate_by_connection_name(self):
        """Only entries for the specified connection should be removed."""
        cache = self._make_cache()
        cache.put("conn1", "SELECT 1", 100, [{"a": 1}], ["t1"], 1.0, "SELECT 1")
        cache.put("conn1", "SELECT 2", 100, [{"b": 2}], ["t2"], 1.0, "SELECT 2")
        cache.put("conn2", "SELECT 3", 100, [{"c": 3}], ["t3"], 1.0, "SELECT 3")

        count = cache.invalidate("conn1")
        assert count == 2

        # conn1 entries gone
        assert cache.get("conn1", "SELECT 1", 100) is None
        assert cache.get("conn1", "SELECT 2", 100) is None

        # conn2 entry still present
        entry = cache.get("conn2", "SELECT 3", 100)
        assert entry is not None
        assert entry.rows == [{"c": 3}]

    def test_hit_rate_tracking(self):
        cache = self._make_cache()
        cache.put("c", "SELECT 1", 100, [], [], 1.0, "SELECT 1")
        cache.get("c", "SELECT 1", 100)  # hit
        cache.get("c", "SELECT 999", 100)  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_eviction_at_capacity(self):
        cache = QueryCache(max_entries=2, ttl_seconds=300)
        cache.put("c", "q1", 100, [], [], 1.0, "q1")
        cache.put("c", "q2", 100, [], [], 1.0, "q2")
        cache.put("c", "q3", 100, [], [], 1.0, "q3")  # should evict q1
        assert cache.stats()["entries"] == 2
