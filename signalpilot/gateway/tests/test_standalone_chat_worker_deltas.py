"""DeltaBatcher: streamed deltas coalesce into few events, in order."""

from __future__ import annotations

import asyncio

import pytest

from gateway.standalone_chat import worker_deltas
from gateway.standalone_chat.worker_deltas import DeltaBatcher


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def write(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


@pytest.fixture
def fast_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_deltas, "FLUSH_INTERVAL_SECONDS", 0.02)


async def test_consecutive_text_deltas_become_one_event(fast_interval: None):
    sink = Sink()
    batcher = DeltaBatcher(sink.write)
    for chunk in ("Rev", "enue ", "grew", " 12%"):
        await batcher.add("text_delta", {"delta": chunk})
    assert sink.events == []
    await batcher.flush()
    assert sink.events == [("text_delta", {"delta": "Revenue grew 12%"})]


async def test_timer_flushes_without_a_following_event(fast_interval: None):
    sink = Sink()
    batcher = DeltaBatcher(sink.write)
    await batcher.add("text_delta", {"delta": "hello"})
    await asyncio.sleep(0.08)
    assert sink.events == [("text_delta", {"delta": "hello"})]
    await batcher.close()


async def test_type_change_splits_events_in_order(fast_interval: None):
    sink = Sink()
    batcher = DeltaBatcher(sink.write)
    await batcher.add("thinking_delta", {"delta": "let me "})
    await batcher.add("thinking_delta", {"delta": "check"})
    await batcher.add("text_delta", {"delta": "Answer"})
    await batcher.close()
    assert sink.events == [
        ("thinking_delta", {"delta": "let me check"}),
        ("text_delta", {"delta": "Answer"}),
    ]


async def test_parent_change_splits_and_keeps_parent(fast_interval: None):
    sink = Sink()
    batcher = DeltaBatcher(sink.write)
    await batcher.add("text_delta", {"delta": "main"})
    await batcher.add("text_delta", {"delta": "sub", "parent_tool_call_id": "t1"})
    await batcher.add("text_delta", {"delta": "agent", "parent_tool_call_id": "t1"})
    await batcher.close()
    assert sink.events == [
        ("text_delta", {"delta": "main"}),
        ("text_delta", {"delta": "subagent", "parent_tool_call_id": "t1"}),
    ]


async def test_large_buffer_flushes_immediately(monkeypatch: pytest.MonkeyPatch, fast_interval: None):
    monkeypatch.setattr(worker_deltas, "FLUSH_MAX_CHARS", 10)
    sink = Sink()
    batcher = DeltaBatcher(sink.write)
    await batcher.add("text_delta", {"delta": "12345"})
    await batcher.add("text_delta", {"delta": "67890"})
    assert sink.events == [("text_delta", {"delta": "1234567890"})]
    await batcher.close()


async def test_empty_deltas_are_ignored(fast_interval: None):
    sink = Sink()
    batcher = DeltaBatcher(sink.write)
    await batcher.add("text_delta", {"delta": ""})
    await batcher.close()
    assert sink.events == []


async def test_flush_is_idempotent_and_close_stops_the_timer(fast_interval: None):
    sink = Sink()
    batcher = DeltaBatcher(sink.write)
    await batcher.add("text_delta", {"delta": "x"})
    await batcher.flush()
    await batcher.flush()
    await batcher.close()
    await asyncio.sleep(0.05)
    assert sink.events == [("text_delta", {"delta": "x"})]


class FailingSink(Sink):
    async def write(self, event_type: str, payload: dict) -> None:
        raise RuntimeError("database unavailable")


async def test_timer_flush_failure_is_logged_not_raised(
    fast_interval: None, caplog: pytest.LogCaptureFixture
):
    sink = FailingSink()
    batcher = DeltaBatcher(sink.write)
    with caplog.at_level("WARNING", logger="gateway.standalone_chat.worker_deltas"):
        await batcher.add("text_delta", {"delta": "lost"})
        await asyncio.sleep(0.08)
    assert "Timed flush of streamed deltas failed" in caplog.text
    # The failed chunk is dropped; later chunks still flow, and close() is clean.
    await batcher.close()
    assert sink.events == []


async def test_explicit_flush_raises_the_writer_error(fast_interval: None):
    batcher = DeltaBatcher(FailingSink().write)
    await batcher.add("text_delta", {"delta": "x"})
    with pytest.raises(RuntimeError, match="database unavailable"):
        await batcher.flush()
    await batcher.close()


async def test_worker_append_routes_deltas_through_the_batcher(monkeypatch: pytest.MonkeyPatch, fast_interval: None):
    from gateway.standalone_chat import worker

    written: list[tuple[str, str, dict]] = []

    async def fake_write(run_id: str, event_type: str, payload: dict) -> None:
        written.append((run_id, event_type, payload))

    monkeypatch.setattr(worker, "_write_event", fake_write)
    worker._delta_batchers["run-1"] = DeltaBatcher(
        lambda event_type, payload: fake_write("run-1", event_type, payload)
    )
    try:
        await worker._append("run-1", "text_delta", {"delta": "a"})
        await worker._append("run-1", "text_delta", {"delta": "b"})
        await worker._append("run-1", "tool_started", {"tool": "t"})
        await worker._append("run-1", "text_delta", {"delta": "c"})
        await worker._append("run-2", "text_delta", {"delta": "direct"})
        await worker._delta_batchers["run-1"].close()
    finally:
        worker._delta_batchers.pop("run-1", None)
    assert written == [
        ("run-1", "text_delta", {"delta": "ab"}),
        ("run-1", "tool_started", {"tool": "t"}),
        ("run-2", "text_delta", {"delta": "direct"}),
        ("run-1", "text_delta", {"delta": "c"}),
    ]
