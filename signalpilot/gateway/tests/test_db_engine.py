"""Tests for gateway/db/engine.py SSL detection logic."""

from __future__ import annotations

import pytest

from gateway.db.engine import _requires_ssl


class TestRequiresSsl:
    def test_requires_ssl_detects_channel_binding(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?channel_binding=require")
        assert _requires_ssl() is True

    def test_requires_ssl_detects_ssl_true(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?ssl=true")
        assert _requires_ssl() is True

    def test_requires_ssl_sslmode_require(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?sslmode=require")
        assert _requires_ssl() is True

    def test_requires_ssl_sslmode_disable_is_false(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?sslmode=disable")
        assert _requires_ssl() is False

    def test_requires_ssl_no_url(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert _requires_ssl() is False

    def test_requires_ssl_sslmode_verify_ca(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?sslmode=verify-ca")
        assert _requires_ssl() is True

    def test_requires_ssl_sslmode_verify_full(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?sslmode=verify-full")
        assert _requires_ssl() is True
