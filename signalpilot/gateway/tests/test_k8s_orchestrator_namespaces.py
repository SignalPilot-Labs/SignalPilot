"""Tests for per-org tenant namespace behavior (eval workloads)."""

from __future__ import annotations

import pytest


class TestIs409Classification:
    """R5: _is_409 must use exc.status, not str(exc)."""

    def test_returns_true_for_status_409(self):
        from gateway.orchestrator.namespaces import _is_409

        exc = type("E", (Exception,), {})()
        exc.status = 409  # type: ignore[attr-defined]
        assert _is_409(exc) is True

    def test_returns_false_for_status_500(self):
        from gateway.orchestrator.namespaces import _is_409

        exc = type("E", (Exception,), {})()
        exc.status = 500  # type: ignore[attr-defined]
        assert _is_409(exc) is False

    def test_returns_false_for_plain_exception_with_409_in_message(self):
        """Proves we no longer grep — '409' in the message text must not count."""
        from gateway.orchestrator.namespaces import _is_409

        assert _is_409(Exception("409 oops AlreadyExists")) is False
