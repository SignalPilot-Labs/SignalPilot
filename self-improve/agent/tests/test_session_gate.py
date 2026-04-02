"""Tests for the session gate time-lock module."""

import time
import pytest

from agent import session_gate


@pytest.fixture(autouse=True)
def reset_state():
    """Reset session gate state between tests."""
    session_gate._run_start = 0.0
    session_gate._run_duration_sec = 0.0
    session_gate._force_unlocked = False
    session_gate._run_id = None
    session_gate._session_ended = False
    yield


class TestConfigure:
    def test_sets_duration(self):
        session_gate.configure("run-1", duration_minutes=30)
        assert session_gate._run_duration_sec == 1800
        assert session_gate._run_id == "run-1"
        assert session_gate._session_ended is False

    def test_resets_force_unlock(self):
        session_gate._force_unlocked = True
        session_gate.configure("run-2", duration_minutes=10)
        assert session_gate._force_unlocked is False


class TestIsUnlocked:
    def test_unlocked_when_no_duration(self):
        session_gate.configure("run-1", duration_minutes=0)
        assert session_gate.is_unlocked() is True

    def test_locked_during_duration(self):
        session_gate.configure("run-1", duration_minutes=60)
        assert session_gate.is_unlocked() is False

    def test_unlocked_after_duration(self):
        session_gate._run_start = time.time() - 100
        session_gate._run_duration_sec = 50
        assert session_gate.is_unlocked() is True

    def test_force_unlock(self):
        session_gate.configure("run-1", duration_minutes=60)
        assert session_gate.is_unlocked() is False
        session_gate.force_unlock()
        assert session_gate.is_unlocked() is True


class TestTimeRemaining:
    def test_zero_when_expired(self):
        session_gate._run_start = time.time() - 100
        session_gate._run_duration_sec = 50
        assert session_gate.time_remaining_str() == "0m"

    def test_shows_minutes(self):
        session_gate._run_start = time.time()
        session_gate._run_duration_sec = 600  # 10 minutes
        result = session_gate.time_remaining_str()
        assert "m" in result
        # Should be close to 10m (9m or 10m depending on timing)
        minutes = int(result.replace("m", ""))
        assert 8 <= minutes <= 10

    def test_shows_hours_and_minutes(self):
        session_gate._run_start = time.time()
        session_gate._run_duration_sec = 5400  # 90 minutes
        result = session_gate.time_remaining_str()
        assert "h" in result


class TestElapsedMinutes:
    def test_returns_elapsed(self):
        session_gate._run_start = time.time() - 120  # 2 minutes ago
        elapsed = session_gate.elapsed_minutes()
        assert 1.9 <= elapsed <= 2.2


class TestHasEnded:
    def test_false_initially(self):
        assert session_gate.has_ended() is False

    def test_true_after_set(self):
        session_gate._session_ended = True
        assert session_gate.has_ended() is True


class TestBuildDenialMessage:
    def test_includes_remaining_time(self):
        session_gate._run_start = time.time()
        session_gate._run_duration_sec = 600
        msg = session_gate.build_denial_message()
        assert "SESSION LOCKED" in msg
        assert "remaining" in msg
