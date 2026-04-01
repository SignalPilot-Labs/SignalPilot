"""Tests for PII detection and redaction (Features #14-15)."""

import pytest

from signalpilot.gateway.gateway.governance.pii import (
    PIIRedactor,
    PIIRule,
    detect_pii_columns,
    _hash_value,
    _mask_value,
)


class TestPIIRedactor:
    """Tests for the PIIRedactor class."""

    def test_no_rules_passthrough(self):
        redactor = PIIRedactor()
        rows = [{"id": 1, "name": "Alice"}]
        result = redactor.redact_rows(rows)
        assert result == rows

    def test_hash_rule(self):
        redactor = PIIRedactor()
        redactor.add_rule("ssn", PIIRule.hash)
        rows = [{"id": 1, "ssn": "123-45-6789"}]
        result = redactor.redact_rows(rows)
        assert result[0]["ssn"].startswith("sha256:")
        assert result[0]["id"] == 1

    def test_mask_email(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.mask)
        rows = [{"email": "john@example.com"}]
        result = redactor.redact_rows(rows)
        assert "j***@example.com" == result[0]["email"]

    def test_mask_phone(self):
        redactor = PIIRedactor()
        redactor.add_rule("phone", PIIRule.mask)
        rows = [{"phone": "555-123-4567"}]
        result = redactor.redact_rows(rows)
        assert result[0]["phone"].endswith("4567")
        assert "***" in result[0]["phone"]

    def test_drop_rule(self):
        redactor = PIIRedactor()
        redactor.add_rule("password", PIIRule.drop)
        rows = [{"id": 1, "password": "secret123"}]
        result = redactor.redact_rows(rows)
        assert "password" not in result[0]
        assert result[0]["id"] == 1

    def test_case_insensitive_matching(self):
        redactor = PIIRedactor()
        redactor.add_rule("EMAIL", PIIRule.mask)
        rows = [{"email": "test@test.com"}]
        result = redactor.redact_rows(rows)
        assert "***" in result[0]["email"]

    def test_last_redacted_columns(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.mask)
        redactor.add_rule("ssn", PIIRule.hash)
        rows = [{"email": "a@b.com", "ssn": "111-22-3333", "name": "Test"}]
        redactor.redact_rows(rows)
        assert "email" in redactor.last_redacted_columns
        assert "ssn" in redactor.last_redacted_columns
        assert "name" not in redactor.last_redacted_columns

    def test_null_handling(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.hash)
        rows = [{"email": None}]
        result = redactor.redact_rows(rows)
        assert result[0]["email"] == "NULL"

    def test_multiple_rows(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.mask)
        rows = [
            {"id": 1, "email": "alice@example.com"},
            {"id": 2, "email": "bob@example.com"},
        ]
        result = redactor.redact_rows(rows)
        assert len(result) == 2
        assert "a***@example.com" == result[0]["email"]
        assert "b***@example.com" == result[1]["email"]

    def test_empty_rows(self):
        redactor = PIIRedactor()
        redactor.add_rule("email", PIIRule.mask)
        result = redactor.redact_rows([])
        assert result == []


class TestPIIAutoDetection:
    """Tests for detect_pii_columns() auto-detection."""

    def test_detects_email(self):
        detected = detect_pii_columns(["id", "email", "name"])
        assert "email" in detected
        assert detected["email"] == PIIRule.mask

    def test_detects_ssn(self):
        detected = detect_pii_columns(["ssn", "first_name"])
        assert "ssn" in detected
        assert detected["ssn"] == PIIRule.hash

    def test_detects_password(self):
        detected = detect_pii_columns(["password", "username"])
        assert "password" in detected
        assert detected["password"] == PIIRule.drop

    def test_detects_phone_number(self):
        detected = detect_pii_columns(["phone_number"])
        assert "phone_number" in detected
        assert detected["phone_number"] == PIIRule.mask

    def test_no_false_positives_on_safe_columns(self):
        detected = detect_pii_columns(["id", "created_at", "status", "count", "total"])
        assert len(detected) == 0

    def test_case_insensitive(self):
        detected = detect_pii_columns(["EMAIL_ADDRESS", "SSN"])
        assert len(detected) == 2

    def test_partial_match(self):
        """Column names containing PII keywords should be detected."""
        detected = detect_pii_columns(["user_email", "customer_phone"])
        assert "user_email" in detected
        assert "customer_phone" in detected

    def test_api_key_detected(self):
        detected = detect_pii_columns(["api_key", "access_token"])
        assert "api_key" in detected
        assert detected["api_key"] == PIIRule.drop
        assert "access_token" in detected
        assert detected["access_token"] == PIIRule.drop

    def test_financial_columns(self):
        detected = detect_pii_columns(["credit_card", "bank_account", "routing_number"])
        assert all(detected[col] == PIIRule.hash for col in detected)


class TestMaskingFunctions:
    """Tests for individual masking functions."""

    def test_hash_deterministic(self):
        assert _hash_value("test") == _hash_value("test")

    def test_hash_different_inputs(self):
        assert _hash_value("a") != _hash_value("b")

    def test_mask_short_string(self):
        assert _mask_value("ab") == "***"

    def test_mask_generic(self):
        result = _mask_value("John Doe")
        assert result.startswith("J")
        assert result.endswith("e")
        assert "***" in result
