"""Tests for the signal queue module."""

import asyncio
import pytest

from agent import signals


@pytest.fixture(autouse=True)
def reset_signals():
    """Ensure signal queue is torn down between tests."""
    signals.teardown()
    yield
    signals.teardown()


def test_init_creates_queue():
    signals.init()
    assert signals._signal_queue is not None


def test_teardown_clears_queue():
    signals.init()
    signals.teardown()
    assert signals._signal_queue is None


def test_push_without_init_does_not_raise():
    # Should silently no-op when queue is None
    signals.push("stop", "test")


@pytest.mark.asyncio
async def test_push_and_drain():
    signals.init()
    signals.push("pause")
    result = await signals.drain()
    assert result is not None
    assert result["signal"] == "pause"
    assert result["payload"] is None


@pytest.mark.asyncio
async def test_push_with_payload():
    signals.init()
    signals.push("inject", "do something")
    result = await signals.drain()
    assert result["signal"] == "inject"
    assert result["payload"] == "do something"


@pytest.mark.asyncio
async def test_drain_empty_returns_none():
    signals.init()
    result = await signals.drain()
    assert result is None


@pytest.mark.asyncio
async def test_drain_without_init_returns_none():
    result = await signals.drain()
    assert result is None


@pytest.mark.asyncio
async def test_wait_timeout_returns_none():
    signals.init()
    result = await signals.wait(timeout=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_wait_receives_signal():
    signals.init()

    async def push_later():
        await asyncio.sleep(0.02)
        signals.push("resume")

    asyncio.create_task(push_later())
    result = await signals.wait(timeout=1.0)
    assert result is not None
    assert result["signal"] == "resume"


@pytest.mark.asyncio
async def test_wait_without_init_returns_none():
    result = await signals.wait(timeout=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_multiple_signals_fifo():
    signals.init()
    signals.push("pause")
    signals.push("inject", "msg1")
    signals.push("resume")

    r1 = await signals.drain()
    r2 = await signals.drain()
    r3 = await signals.drain()

    assert r1["signal"] == "pause"
    assert r2["signal"] == "inject"
    assert r2["payload"] == "msg1"
    assert r3["signal"] == "resume"
