"""Unit tests for signalpilot._server.auth.session_token."""
from __future__ import annotations

import os
import threading
from unittest.mock import patch

import pytest

from signalpilot._server.auth.session_token import _reset_for_test, load_session_jwt


@pytest.fixture(autouse=True)
def _reset_token_state():
    """Reset module-level cache before and after every test."""
    _reset_for_test()
    yield
    _reset_for_test()


class TestLoadSessionJwt:
    def test_first_call_pops_env(self):
        """First call returns the env value and removes it from os.environ."""
        os.environ["SP_SESSION_JWT"] = "abc"
        try:
            result = load_session_jwt()
            assert result == "abc"
            assert "SP_SESSION_JWT" not in os.environ
        finally:
            os.environ.pop("SP_SESSION_JWT", None)

    def test_cache_wins_after_env_remutated(self):
        """Second call returns cached value even if env is re-set to something else."""
        os.environ["SP_SESSION_JWT"] = "abc"
        try:
            load_session_jwt()
            os.environ["SP_SESSION_JWT"] = "zzz"
            result = load_session_jwt()
            assert result == "abc"
        finally:
            os.environ.pop("SP_SESSION_JWT", None)

    def test_empty_env_returns_empty_string(self):
        """When env var is absent, load_session_jwt returns empty string."""
        os.environ.pop("SP_SESSION_JWT", None)
        result = load_session_jwt()
        assert result == ""

    def test_idempotent_second_call(self):
        """Subsequent calls return the same cached value without re-reading env."""
        os.environ["SP_SESSION_JWT"] = "first"
        try:
            first = load_session_jwt()
            os.environ.pop("SP_SESSION_JWT", None)
            second = load_session_jwt()
            assert first == second == "first"
        finally:
            os.environ.pop("SP_SESSION_JWT", None)

    def test_thread_safety_single_consumer(self):
        """50 threads racing on first call — all return identical value, env popped once."""
        os.environ["SP_SESSION_JWT"] = "shared-token"
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            val = load_session_jwt()
            with lock:
                results.append(val)

        try:
            threads = [threading.Thread(target=worker) for _ in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert all(r == "shared-token" for r in results)
            assert len(results) == 50
            assert "SP_SESSION_JWT" not in os.environ
        finally:
            os.environ.pop("SP_SESSION_JWT", None)
