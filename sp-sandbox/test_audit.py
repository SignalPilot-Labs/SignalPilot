"""Tests for the sandbox audit logging module (sp-sandbox/audit.py)."""

from __future__ import annotations

import hashlib
import json
import logging
from unittest.mock import patch

import pytest

import audit


def _make_log_execution_kwargs(**overrides) -> dict:
    defaults = {
        "session_token": "abc123def456",
        "vm_id": "vm-test-001",
        "code_length": 42,
        "code_hash": audit.hash_code_for_audit("print('hello')"),
        "timeout": 30,
        "mount_count": 0,
        "success": True,
        "error": None,
        "execution_ms": 123.45,
        "client_ip": "172.18.0.1",
    }
    defaults.update(overrides)
    return defaults


class TestAuditLogExecution:
    """Tests for audit.log_execution()."""

    def test_log_execution_emits_json(self, caplog):
        """log_execution emits a parseable JSON line with all expected fields."""
        kwargs = _make_log_execution_kwargs()
        with caplog.at_level(logging.INFO, logger="sandbox_audit"):
            audit.log_execution(**kwargs)

        assert caplog.records, "Expected at least one log record"
        record = caplog.records[0]
        payload = json.loads(record.getMessage())

        assert payload["event"] == "sandbox_execution"
        assert "timestamp" in payload
        assert "session_token" in payload
        assert "vm_id" in payload
        assert "code_length" in payload
        assert "code_hash" in payload
        assert "timeout" in payload
        assert "mount_count" in payload
        assert "success" in payload
        assert "error" in payload
        assert "execution_ms" in payload
        assert "client_ip" in payload

    def test_log_execution_truncates_session_token(self, caplog):
        """session_token in the JSON payload must be at most 8 characters."""
        long_token = "abcdef1234567890longtoken"
        kwargs = _make_log_execution_kwargs(session_token=long_token)
        with caplog.at_level(logging.INFO, logger="sandbox_audit"):
            audit.log_execution(**kwargs)

        payload = json.loads(caplog.records[0].getMessage())
        assert len(payload["session_token"]) <= 8
        assert payload["session_token"] == long_token[:8]

    def test_log_execution_uses_utc_timestamp(self, caplog):
        """Timestamp must be UTC, indicated by +00:00 or Z suffix."""
        kwargs = _make_log_execution_kwargs()
        with caplog.at_level(logging.INFO, logger="sandbox_audit"):
            audit.log_execution(**kwargs)

        payload = json.loads(caplog.records[0].getMessage())
        timestamp = payload["timestamp"]
        assert timestamp.endswith("+00:00") or timestamp.endswith("Z"), (
            f"Timestamp {timestamp!r} does not indicate UTC"
        )

    def test_log_execution_does_not_raise_on_failure(self, caplog):
        """log_execution must swallow internal errors and log a warning instead."""
        kwargs = _make_log_execution_kwargs()
        with caplog.at_level(logging.WARNING, logger="sandbox_audit"):
            with patch.object(audit.logger, "info", side_effect=RuntimeError("boom")):
                # Must not raise
                audit.log_execution(**kwargs)

        warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("audit log failed" in msg for msg in warning_messages), (
            "Expected a warning about audit log failure"
        )

    def test_log_execution_hashes_code(self, caplog):
        """code_hash must equal SHA-256 of the code string."""
        code = "import os; print(os.environ)"
        expected_hash = hashlib.sha256(code.encode()).hexdigest()

        computed_hash = audit.hash_code_for_audit(code)
        assert computed_hash == expected_hash

        kwargs = _make_log_execution_kwargs(code_hash=computed_hash)
        with caplog.at_level(logging.INFO, logger="sandbox_audit"):
            audit.log_execution(**kwargs)

        payload = json.loads(caplog.records[0].getMessage())
        assert payload["code_hash"] == expected_hash
