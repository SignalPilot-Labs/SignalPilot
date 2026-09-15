"""Sandbox panel for the containers that execute an eval run.

The routes provide read-only access within one organization. The view layer
does not return pod or container specifications, and it redacts free text to
prevent credential disclosure. ``eval_runs.py`` mounts this router with the
read-tier eval guards (read scope plus a billable plan).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..evals import sandboxes
from .deps import StoreD

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_LOG_STREAMS: int = 8
_LOG_HEARTBEAT_SECONDS: float = 10.0
_log_stream_semaphore = asyncio.Semaphore(MAX_LOG_STREAMS)


def _safe_sandbox_name(name: str) -> str:
    if not sandboxes.is_valid_sandbox_name(name):
        raise HTTPException(status_code=400, detail="Invalid sandbox name")
    return name


@router.get("/evals/sandboxes")
async def list_eval_sandboxes(store: StoreD):
    """Eval containers alive right now for the caller's org."""
    view = sandboxes.get_sandbox_view(store.org_id)
    try:
        return await view.inventory()
    finally:
        await view.aclose()


@router.get("/evals/sandboxes/{name}/events")
async def get_eval_sandbox_events(store: StoreD, name: str):
    """Recent Kubernetes events for a sandbox pod: what makes a stuck pod
    diagnosable (unschedulable, image pull failure, sandbox runtime error)."""
    view = sandboxes.get_sandbox_view(store.org_id)
    try:
        return await view.events(_safe_sandbox_name(name))
    finally:
        await view.aclose()


@router.get("/evals/sandboxes/{name}/logs/stream")
async def stream_eval_sandbox_logs(
    store: StoreD, name: str, tail: int = Query(200, ge=1, le=2000)
) -> StreamingResponse:
    """SSE tail of a live sandbox.

    Terminates on its own when the sandbox exits, when the byte cap or the
    wall-clock deadline is hit, or when the viewer disconnects.
    """
    safe_name = _safe_sandbox_name(name)
    if _log_stream_semaphore.locked():
        raise HTTPException(
            status_code=429,
            detail="Too many sandbox log streams open. Close one and retry.",
            headers={"Retry-After": "15"},
        )
    view = sandboxes.get_sandbox_view(store.org_id)

    async def generate():
        await _log_stream_semaphore.acquire()
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        async def pump() -> None:
            try:
                async for kind, payload in view.stream_logs(safe_name, tail_lines=tail):
                    await queue.put((kind, payload))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Eval sandbox log stream for %s failed: %s", safe_name, exc)
                await queue.put(("error", f"log stream failed: {type(exc).__name__}"))
                await queue.put(("end", "stream-error"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump())
        try:
            yield _sse({"type": "open", "sandbox": safe_name, "at": time.time()})
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_LOG_HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield _sse({"type": "heartbeat", "at": time.time()})
                    continue
                if item is None:
                    return
                kind, payload = item
                if kind == "end":
                    yield _sse({"type": "end", "reason": payload, "at": time.time()})
                    return
                yield _sse({"type": kind, "text": sandboxes.redact(payload), "at": time.time()})
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            await view.aclose()
            _log_stream_semaphore.release()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"
