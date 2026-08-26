"""Fire-and-forget asyncio task scheduling with strong references.

The event loop keeps only weak references to tasks; without a strong ref a
pending background task can be garbage-collected before it runs.
"""

from __future__ import annotations

import asyncio

_bg_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro) -> asyncio.Task | None:
    """Schedule a coroutine without awaiting it, holding a strong reference.

    Returns the task, or None when no event loop is running (sync test
    contexts) — the coroutine is closed in that case.
    """
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        return None
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task
