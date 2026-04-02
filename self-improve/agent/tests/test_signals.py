"""Unit tests for the signals module (agent/signals.py).

Covers:
- init_signal_queue / teardown_signal_queue lifecycle
- push_signal / drain_signal round-trip and edge cases
- wait_for_signal happy path and timeout
- FIFO ordering across multiple signals
- start_pulse_checker / stop_pulse_checker task management
"""

import sys
import asyncio
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out heavy dependencies before importing the module under test
# ---------------------------------------------------------------------------
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())
sys.modules.setdefault("agent.db", MagicMock())
sys.modules.setdefault("agent.hooks", MagicMock())
sys.modules.setdefault("agent.session_gate", MagicMock())

from agent import signals  # noqa: E402  (import after mock setup)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_queue():
    """Ensure a clean signal queue before and after every test."""
    signals.teardown_signal_queue()
    yield
    signals.teardown_signal_queue()


# ---------------------------------------------------------------------------
# init_signal_queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_creates_usable_queue():
    """init_signal_queue creates a queue that accepts push and drain."""
    signals.init_signal_queue()
    signals.push_signal("test_event")
    result = await signals.drain_signal()
    assert result is not None
    assert result["signal"] == "test_event"


# ---------------------------------------------------------------------------
# teardown_signal_queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_teardown_makes_push_noop():
    """After teardown, push_signal silently does nothing."""
    signals.init_signal_queue()
    signals.teardown_signal_queue()
    # Should not raise
    signals.push_signal("should_be_ignored")


@pytest.mark.asyncio
async def test_teardown_makes_drain_return_none():
    """After teardown, drain_signal returns None without raising."""
    signals.init_signal_queue()
    signals.teardown_signal_queue()
    result = await signals.drain_signal()
    assert result is None


# ---------------------------------------------------------------------------
# push_signal + drain_signal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_drain_round_trip_signal_only():
    """push_signal with no payload; drain returns correct dict."""
    signals.init_signal_queue()
    signals.push_signal("stop")
    result = await signals.drain_signal()
    assert result == {"signal": "stop", "payload": None}


@pytest.mark.asyncio
async def test_push_drain_round_trip_with_payload():
    """push_signal with a payload is preserved through drain."""
    signals.init_signal_queue()
    signals.push_signal("inject", payload="do something useful")
    result = await signals.drain_signal()
    assert result == {"signal": "inject", "payload": "do something useful"}


@pytest.mark.asyncio
async def test_drain_returns_none_on_empty_queue():
    """drain_signal returns None when the queue exists but is empty."""
    signals.init_signal_queue()
    result = await signals.drain_signal()
    assert result is None


@pytest.mark.asyncio
async def test_drain_returns_none_without_init():
    """drain_signal returns None when queue has never been initialized."""
    # reset_queue fixture already called teardown; queue is None
    result = await signals.drain_signal()
    assert result is None


@pytest.mark.asyncio
async def test_push_noop_without_init():
    """push_signal is a no-op when queue is not initialized."""
    # queue is None (fixture teardown)
    signals.push_signal("stop")  # must not raise
    # Confirm nothing was queued by initializing and draining
    signals.init_signal_queue()
    result = await signals.drain_signal()
    assert result is None


# ---------------------------------------------------------------------------
# wait_for_signal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_for_signal_returns_signal_when_pushed():
    """wait_for_signal returns the signal dict when one is already on the queue."""
    signals.init_signal_queue()
    signals.push_signal("resume")
    result = await signals.wait_for_signal(timeout=1.0)
    assert result == {"signal": "resume", "payload": None}


@pytest.mark.asyncio
async def test_wait_for_signal_returns_signal_pushed_concurrently():
    """wait_for_signal receives a signal pushed by a concurrent coroutine."""
    signals.init_signal_queue()

    async def push_after_delay():
        await asyncio.sleep(0.05)
        signals.push_signal("pause")

    asyncio.create_task(push_after_delay())
    result = await signals.wait_for_signal(timeout=1.0)
    assert result == {"signal": "pause", "payload": None}


@pytest.mark.asyncio
async def test_wait_for_signal_returns_none_on_timeout():
    """wait_for_signal returns None when no signal arrives within timeout."""
    signals.init_signal_queue()
    result = await signals.wait_for_signal(timeout=0.1)
    assert result is None


@pytest.mark.asyncio
async def test_wait_for_signal_returns_none_without_init():
    """wait_for_signal returns None immediately when queue is not initialized."""
    result = await signals.wait_for_signal(timeout=0.1)
    assert result is None


# ---------------------------------------------------------------------------
# FIFO ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_signals_drained_fifo():
    """Signals are returned in the order they were pushed."""
    signals.init_signal_queue()
    payloads = [("stop", None), ("resume", "ctx"), ("inject", "prompt")]
    for sig, pay in payloads:
        signals.push_signal(sig, payload=pay)

    results = []
    for _ in payloads:
        item = await signals.drain_signal()
        assert item is not None
        results.append((item["signal"], item["payload"]))

    assert results == payloads

    # Queue should now be empty
    assert await signals.drain_signal() is None


# ---------------------------------------------------------------------------
# start_pulse_checker / stop_pulse_checker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_pulse_checker_creates_task():
    """start_pulse_checker creates a background asyncio Task."""
    signals.init_signal_queue()
    signals.start_pulse_checker("run-abc")
    try:
        assert signals._pulse_task is not None
        assert isinstance(signals._pulse_task, asyncio.Task)
        assert not signals._pulse_task.done()
    finally:
        signals.stop_pulse_checker()


@pytest.mark.asyncio
async def test_stop_pulse_checker_cancels_task():
    """stop_pulse_checker cancels the background task and clears the reference."""
    signals.init_signal_queue()
    signals.start_pulse_checker("run-xyz")
    task = signals._pulse_task
    signals.stop_pulse_checker()

    assert signals._pulse_task is None
    # Give the event loop a chance to process cancellation
    await asyncio.sleep(0)
    assert task.cancelled()


@pytest.mark.asyncio
async def test_stop_pulse_checker_is_idempotent():
    """stop_pulse_checker is safe to call when no task is running."""
    signals.stop_pulse_checker()  # should not raise
    assert signals._pulse_task is None
