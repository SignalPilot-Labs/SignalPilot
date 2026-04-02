"""Unit tests for session_gate.py.

These tests cover the pure time-lock logic functions. The async end_session_tool
is not tested here because it depends on the db layer. All time.time() calls
are controlled via monkeypatch for determinism.
"""

import agent.session_gate as session_gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_START = 1_000_000.0  # arbitrary epoch second used as a fixed "now"


def _configure(run_id="run-test", duration_minutes=30.0, fake_start=_FAKE_START):
    """Configure session_gate with a controlled start time."""
    # Patch _run_start after configure() so tests own the clock.
    session_gate.configure(run_id, duration_minutes)
    session_gate._run_start = fake_start


# ---------------------------------------------------------------------------
# 1. configure() sets module state correctly
# ---------------------------------------------------------------------------


class TestConfigure:
    def test_sets_run_id(self):
        _configure(run_id="abc-123")
        assert session_gate._run_id == "abc-123"

    def test_sets_duration_in_seconds(self):
        _configure(duration_minutes=45)
        assert session_gate._run_duration_sec == 45 * 60

    def test_resets_force_unlocked(self):
        session_gate._force_unlocked = True  # simulate a prior unlock
        _configure()
        assert session_gate._force_unlocked is False

    def test_resets_session_ended(self):
        session_gate._session_ended = True  # simulate a prior ended session
        _configure()
        assert session_gate._session_ended is False

    def test_is_unlocked_false_immediately_after_configure(self, monkeypatch):
        _configure(duration_minutes=30)
        # Current time == start time, so no time has elapsed.
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        assert session_gate.is_unlocked() is False

    def test_has_ended_false_after_configure(self):
        _configure()
        assert session_gate.has_ended() is False

    def test_elapsed_minutes_near_zero_after_configure(self, monkeypatch):
        _configure()
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        assert session_gate.elapsed_minutes() == 0.0


# ---------------------------------------------------------------------------
# 2. is_unlocked() returns False while the lock is active
# ---------------------------------------------------------------------------


class TestIsUnlockedTimeLock:
    def test_locked_when_time_not_elapsed(self, monkeypatch):
        _configure(duration_minutes=30)
        # Only 10 minutes have elapsed; 30-minute lock is still active.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 10 * 60
        )
        assert session_gate.is_unlocked() is False

    def test_unlocked_exactly_at_expiry(self, monkeypatch):
        _configure(duration_minutes=30)
        # time.time() == start + duration → should be unlocked.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 30 * 60
        )
        assert session_gate.is_unlocked() is True

    def test_unlocked_after_expiry(self, monkeypatch):
        _configure(duration_minutes=30)
        # One second past expiry.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 30 * 60 + 1
        )
        assert session_gate.is_unlocked() is True


# ---------------------------------------------------------------------------
# 3. is_unlocked() is True when duration_minutes == 0 (no lock)
# ---------------------------------------------------------------------------


class TestIsUnlockedNoDuration:
    def test_zero_duration_always_unlocked(self, monkeypatch):
        _configure(duration_minutes=0)
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        assert session_gate.is_unlocked() is True

    def test_negative_duration_always_unlocked(self, monkeypatch):
        _configure(duration_minutes=-5)
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        assert session_gate.is_unlocked() is True


# ---------------------------------------------------------------------------
# 4. force_unlock() overrides an active time lock
# ---------------------------------------------------------------------------


class TestForceUnlock:
    def test_force_unlock_sets_flag(self):
        _configure(duration_minutes=60)
        session_gate.force_unlock()
        assert session_gate._force_unlocked is True

    def test_is_unlocked_true_after_force_unlock(self, monkeypatch):
        _configure(duration_minutes=60)
        # Only 1 minute elapsed — still locked by time.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 60
        )
        assert session_gate.is_unlocked() is False  # confirm it was locked
        session_gate.force_unlock()
        assert session_gate.is_unlocked() is True

    def test_configure_resets_force_unlock(self):
        _configure(duration_minutes=60)
        session_gate.force_unlock()
        assert session_gate._force_unlocked is True
        _configure(duration_minutes=60)  # new run
        assert session_gate._force_unlocked is False


# ---------------------------------------------------------------------------
# 5. time_remaining_str() returns correctly formatted strings
# ---------------------------------------------------------------------------


class TestTimeRemainingStr:
    def test_returns_minutes_only_format(self, monkeypatch):
        _configure(duration_minutes=30)
        # 10 minutes elapsed → 20 minutes remaining.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 10 * 60
        )
        assert session_gate.time_remaining_str() == "20m"

    def test_returns_hours_and_minutes_format(self, monkeypatch):
        _configure(duration_minutes=90)
        # 5 minutes elapsed → 1h 25m remaining.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 5 * 60
        )
        assert session_gate.time_remaining_str() == "1h 25m"

    def test_returns_zero_when_expired(self, monkeypatch):
        _configure(duration_minutes=30)
        # At or past expiry.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 30 * 60
        )
        assert session_gate.time_remaining_str() == "0m"

    def test_returns_zero_when_past_expiry(self, monkeypatch):
        _configure(duration_minutes=10)
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 60 * 60
        )
        assert session_gate.time_remaining_str() == "0m"

    def test_exactly_one_hour_remaining(self, monkeypatch):
        _configure(duration_minutes=60)
        # No time elapsed → 1h 0m remaining.
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        assert session_gate.time_remaining_str() == "1h 0m"


# ---------------------------------------------------------------------------
# 6. elapsed_minutes() returns the correct float value
# ---------------------------------------------------------------------------


class TestElapsedMinutes:
    def test_zero_at_start(self, monkeypatch):
        _configure()
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        assert session_gate.elapsed_minutes() == 0.0

    def test_correct_after_partial_elapsed(self, monkeypatch):
        _configure()
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 7.5 * 60
        )
        assert session_gate.elapsed_minutes() == 7.5

    def test_correct_after_full_duration(self, monkeypatch):
        _configure(duration_minutes=30)
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 30 * 60
        )
        assert session_gate.elapsed_minutes() == 30.0

    def test_fractional_minutes(self, monkeypatch):
        _configure()
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 90  # 1.5 minutes
        )
        assert session_gate.elapsed_minutes() == 1.5


# ---------------------------------------------------------------------------
# 7. has_ended() reflects _session_ended state
# ---------------------------------------------------------------------------


class TestHasEnded:
    def test_false_initially(self):
        _configure()
        assert session_gate.has_ended() is False

    def test_false_after_configure_resets_it(self):
        session_gate._session_ended = True
        _configure()
        assert session_gate.has_ended() is False

    def test_true_when_session_ended_flag_set(self):
        _configure()
        session_gate._session_ended = True
        assert session_gate.has_ended() is True

    def test_toggling_flag_is_reflected(self):
        _configure()
        assert session_gate.has_ended() is False
        session_gate._session_ended = True
        assert session_gate.has_ended() is True
        session_gate._session_ended = False
        assert session_gate.has_ended() is False


# ---------------------------------------------------------------------------
# 8. build_denial_message() contains required content
# ---------------------------------------------------------------------------


class TestBuildDenialMessage:
    def test_contains_session_locked(self, monkeypatch):
        _configure(duration_minutes=30)
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        msg = session_gate.build_denial_message()
        assert "SESSION LOCKED" in msg

    def test_contains_remaining_time(self, monkeypatch):
        _configure(duration_minutes=30)
        # 5 minutes elapsed → 25m remaining.
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 5 * 60
        )
        msg = session_gate.build_denial_message()
        assert "25m" in msg

    def test_contains_remaining_time_with_hours(self, monkeypatch):
        _configure(duration_minutes=90)
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        msg = session_gate.build_denial_message()
        assert "1h 30m" in msg

    def test_contains_zero_when_expired(self, monkeypatch):
        _configure(duration_minutes=10)
        monkeypatch.setattr(
            "agent.session_gate.time.time", lambda: _FAKE_START + 60 * 60
        )
        msg = session_gate.build_denial_message()
        assert "0m" in msg

    def test_message_is_a_string(self, monkeypatch):
        _configure(duration_minutes=30)
        monkeypatch.setattr("agent.session_gate.time.time", lambda: _FAKE_START)
        assert isinstance(session_gate.build_denial_message(), str)
