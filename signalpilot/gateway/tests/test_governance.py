"""Tests for the governance layer — budget, cost estimation, PII redaction."""

import pytest

from gateway.governance.budget import BudgetLedger, SessionBudget
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
    """Test the global budget ledger (DB-backed, requires async + DB setup).

    These tests are skipped because BudgetLedger methods are now async and
    require a running PostgreSQL database. Integration tests cover this via
    the API endpoints.
    """

    @pytest.mark.skip(reason="BudgetLedger is now DB-backed; test via API integration tests")
    def test_placeholder(self):
        pass


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
