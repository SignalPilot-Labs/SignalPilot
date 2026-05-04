"""Tests for stream_pump — RunEvent persistence, bus publish, insert failure aborts."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workspaces_api.agent.stream_pump import pump_stream
from workspaces_api.events.bus import EventBus
from workspaces_api.models import Run
from workspaces_api.states import RunState


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_stream_reader(lines: list[bytes]) -> asyncio.StreamReader:
    """Create a StreamReader with pre-populated content."""
    reader = asyncio.StreamReader(limit=8192)
    for line in lines:
        reader.feed_data(line)
    reader.feed_eof()
    return reader


class TestPumpStream:
    @pytest.mark.asyncio
    async def test_stdout_lines_persisted_and_published(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        run_id = uuid.uuid4()
        bus = EventBus()

        # Create the run row
        async with session_factory() as session:
            run = Run(
                id=run_id,
                workspace_id="ws-test",
                prompt="test",
                state=RunState.running.value,
                inference_mode="local",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        terminate_called: list[tuple[uuid.UUID, str]] = []

        async def mock_terminate(rid: uuid.UUID, reason: str) -> None:
            terminate_called.append((rid, reason))

        reader = _make_stream_reader([b"hello world\n", b"second line\n"])

        events_received: list = []
        async with bus.subscribe(run_id) as q:
            pump_task = asyncio.create_task(
                pump_stream(
                    reader=reader,
                    run_id=run_id,
                    kind="stdout",
                    session_factory=session_factory,
                    bus=bus,
                    terminate_callback=mock_terminate,
                )
            )
            # Drain two events
            for _ in range(2):
                ev = await asyncio.wait_for(q.get(), timeout=5.0)
                events_received.append(ev)
            await pump_task

        assert len(events_received) == 2
        assert events_received[0].kind == "agent.stdout"
        assert events_received[0].payload["line"] == "hello world"
        assert events_received[1].payload["line"] == "second line"
        assert not terminate_called

    @pytest.mark.asyncio
    async def test_stderr_lines_have_correct_kind(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        run_id = uuid.uuid4()
        bus = EventBus()

        async with session_factory() as session:
            run = Run(
                id=run_id,
                workspace_id="ws-test",
                prompt="test",
                state=RunState.running.value,
                inference_mode="local",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        async def mock_terminate(rid: uuid.UUID, reason: str) -> None:
            pass

        reader = _make_stream_reader([b"err line\n"])

        async with bus.subscribe(run_id) as q:
            pump_task = asyncio.create_task(
                pump_stream(
                    reader=reader,
                    run_id=run_id,
                    kind="stderr",
                    session_factory=session_factory,
                    bus=bus,
                    terminate_callback=mock_terminate,
                )
            )
            ev = await asyncio.wait_for(q.get(), timeout=5.0)
            await pump_task

        assert ev.kind == "agent.stderr"
        assert ev.payload["line"] == "err line"

    @pytest.mark.asyncio
    async def test_insert_failure_calls_terminate_and_reraises(self) -> None:
        """DB insert failure must call terminate_callback and propagate the exception."""
        run_id = uuid.uuid4()
        bus = EventBus()

        # Create a session factory that raises on commit
        broken_session = AsyncMock(spec=AsyncSession)
        broken_session.__aenter__ = AsyncMock(return_value=broken_session)
        broken_session.__aexit__ = AsyncMock(return_value=False)
        broken_session.add = MagicMock()
        broken_session.flush = AsyncMock(side_effect=RuntimeError("DB is broken"))

        broken_factory = MagicMock(spec=async_sessionmaker)
        broken_factory.return_value = broken_session

        terminate_called: list[tuple[uuid.UUID, str]] = []

        async def mock_terminate(rid: uuid.UUID, reason: str) -> None:
            terminate_called.append((rid, reason))

        reader = _make_stream_reader([b"some line\n"])

        with pytest.raises(RuntimeError, match="DB is broken"):
            await pump_stream(
                reader=reader,
                run_id=run_id,
                kind="stdout",
                session_factory=broken_factory,  # type: ignore[arg-type]
                bus=bus,
                terminate_callback=mock_terminate,
            )

        assert len(terminate_called) == 1
        assert terminate_called[0][0] == run_id
        assert terminate_called[0][1] == "stream_persist_failed"

    @pytest.mark.asyncio
    async def test_oversize_line_emits_warning_event(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        run_id = uuid.uuid4()
        bus = EventBus()

        async with session_factory() as session:
            run = Run(
                id=run_id,
                workspace_id="ws-test",
                prompt="test",
                state=RunState.running.value,
                inference_mode="local",
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(run)
            await session.commit()

        async def mock_terminate(rid: uuid.UUID, reason: str) -> None:
            pass

        # StreamReader default limit is 8192; feed data > limit without newline
        # then a valid line, to trigger LimitOverrunError then normal completion
        big_chunk = b"X" * 8193  # exceeds 8192 limit
        reader = asyncio.StreamReader(limit=8192)
        reader.feed_data(big_chunk)
        reader.feed_data(b"\nnormal line\n")
        reader.feed_eof()

        events_received: list = []
        async with bus.subscribe(run_id) as q:
            pump_task = asyncio.create_task(
                pump_stream(
                    reader=reader,
                    run_id=run_id,
                    kind="stdout",
                    session_factory=session_factory,
                    bus=bus,
                    terminate_callback=mock_terminate,
                )
            )
            # Collect up to 3 events (warning + normal line)
            for _ in range(2):
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=3.0)
                    events_received.append(ev)
                except TimeoutError:
                    break
            await pump_task

        kinds = [ev.kind for ev in events_received]
        assert "agent.stream_warning" in kinds
