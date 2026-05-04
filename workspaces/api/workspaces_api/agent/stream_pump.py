"""Async stream pump — reads stdout/stderr lines from a subprocess and persists them.

Each line is stored as a RunEvent(kind="agent.stdout" | "agent.stderr") and
published to the EventBus. Oversize lines (> _MAX_LINE_BYTES) are dropped and
a warning event is emitted instead.

On DB insert failure: awaits terminate_callback(run_id, "stream_persist_failed")
and re-raises — no log-and-continue.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workspaces_api.events.bus import EventBus
from workspaces_api.models import RunEvent
from workspaces_api.schemas import RunEventOut

logger = logging.getLogger(__name__)

_MAX_LINE_BYTES = 8192


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _persist_event(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    kind: str,
    payload: dict,
) -> RunEvent:
    """Persist a RunEvent row and return it with id populated.

    expire_on_commit=False is set on the session factory, so attributes are
    accessible after commit without a refresh round-trip.
    """
    async with session_factory() as session:
        ev = RunEvent(run_id=run_id, kind=kind, payload=payload)
        session.add(ev)
        await session.flush()
        # Capture id before commit (autoincrement is assigned at flush time)
        _ = ev.id
        await session.commit()
        return ev


def _event_to_out(ev: RunEvent) -> RunEventOut:
    return RunEventOut.model_validate(ev)


async def pump_stream(
    reader: asyncio.StreamReader,
    run_id: uuid.UUID,
    kind: Literal["stdout", "stderr"],
    session_factory: async_sessionmaker[AsyncSession],
    bus: EventBus,
    terminate_callback: Callable[[uuid.UUID, str], Awaitable[None]],
) -> None:
    """Read lines from reader, persist as RunEvents, publish to bus.

    Reads using readuntil(b"\\n") with an 8 KiB cap. Terminates cleanly on EOF.

    On insert failure: awaits terminate_callback and re-raises.
    On oversize line: emits a warning event (does NOT terminate).
    On read error (not insert): emits an agent.stream_error event, returns.
    """
    event_kind = f"agent.{kind}"

    while True:
        try:
            line_bytes = await reader.readuntil(b"\n")
        except asyncio.LimitOverrunError:
            # Line exceeds buffer limit — drain and emit a warning event
            await reader.read(_MAX_LINE_BYTES)
            warning_payload: dict = {
                "warning": "line_truncated",
                "stream": kind,
                "max_bytes": _MAX_LINE_BYTES,
            }
            try:
                ev = await _persist_event(
                    session_factory, run_id, "agent.stream_warning", warning_payload
                )
                await bus.publish(run_id, _event_to_out(ev))
            except Exception as insert_exc:
                logger.error(
                    "stream_pump warning insert failed run_id=%s: %r",
                    run_id,
                    insert_exc,
                )
                await terminate_callback(run_id, "stream_persist_failed")
                raise
            continue
        except asyncio.IncompleteReadError:
            # EOF — normal stream end
            break
        except Exception as read_exc:
            logger.error(
                "stream_pump read error run_id=%s stream=%s: %r",
                run_id,
                kind,
                read_exc,
            )
            error_payload: dict = {
                "error": "read_error",
                "stream": kind,
                "exc_type": type(read_exc).__name__,
            }
            try:
                ev = await _persist_event(
                    session_factory, run_id, "agent.stream_error", error_payload
                )
                await bus.publish(run_id, _event_to_out(ev))
            except Exception:
                pass  # Best-effort; do not cascade
            return

        line_text = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
        payload: dict = {"line": line_text}

        try:
            ev = await _persist_event(session_factory, run_id, event_kind, payload)
        except Exception as insert_exc:
            logger.error(
                "stream_pump insert failed run_id=%s stream=%s: %r — terminating run",
                run_id,
                kind,
                insert_exc,
            )
            await terminate_callback(run_id, "stream_persist_failed")
            raise

        await bus.publish(run_id, _event_to_out(ev))
