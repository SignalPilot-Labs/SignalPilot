# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path

import watchdog.events  # type: ignore[import-not-found,import-untyped,unused-ignore]
import watchdog.observers  # type: ignore[import-not-found,import-untyped,unused-ignore]

from signalpilot import _loggers

LOGGER = _loggers.sp_logger()

Callback = Callable[[Path], Coroutine[None, None, None]]


class FileWatcher(watchdog.events.PatternMatchingEventHandler):
    def __init__(
        self,
        path: Path,
        callback: Callback,
        loop: asyncio.AbstractEventLoop,
    ):
        self.path = path
        self.callback = callback
        self.loop = loop
        self.observer = watchdog.observers.Observer()

    async def on_file_changed(self) -> None:
        LOGGER.debug(f"File at {self.path} was modified.")
        await self.callback(self.path)

    def on_modified(
        self,
        event: watchdog.events.FileModifiedEvent
        | watchdog.events.DirModifiedEvent,
    ) -> None:
        del event
        asyncio.run_coroutine_threadsafe(self.on_file_changed(), self.loop)

    def on_moved(
        self,
        event: watchdog.events.FileMovedEvent
        | watchdog.events.DirMovedEvent,
    ) -> None:
        # Handle editors that save by creating a temp file and moving it
        # (e.g., Claude Code, some vim configurations)
        dest_path_str = (
            event.dest_path
            if isinstance(event.dest_path, str)
            else event.dest_path.decode("utf-8")
        )

        if self.path == Path(dest_path_str):
            asyncio.run_coroutine_threadsafe(
                self.on_file_changed(), self.loop
            )

    def start(self) -> None:
        event_handler = watchdog.events.PatternMatchingEventHandler(  # type: ignore
            patterns=[str(self.path)]
        )
        event_handler.on_modified = self.on_modified  # type: ignore
        event_handler.on_moved = self.on_moved  # type: ignore
        self.observer.schedule(  # type: ignore
            event_handler,
            str(self.path.parent),
            recursive=False,
        )
        self.observer.start()  # type: ignore

    def stop(self) -> None:
        self.observer.stop()  # type: ignore
        self.observer.join()


FileCallback = Callable[[Path], Awaitable[None]]


class FileWatcherManager:
    """Manages multiple file watchers, sharing watchers for the same file."""

    def __init__(self) -> None:
        # Map of file paths to their watchers
        self._watchers: dict[str, FileWatcher] = {}
        # Map of file paths to their callbacks
        self._callbacks: dict[str, set[FileCallback]] = defaultdict(set)

    def add_callback(self, path: Path, callback: FileCallback) -> None:
        """Add a callback for a file path. Creates watcher if needed."""
        path_str = str(path)
        self._callbacks[path_str].add(callback)

        if path_str not in self._watchers:

            async def shared_callback(changed_path: Path) -> None:
                callbacks = self._callbacks.get(str(changed_path), set())
                # Iterate over a copy to avoid "Set changed size during iteration"
                # if a callback modifies the callbacks set
                for cb in list(callbacks):
                    await cb(changed_path)

            watcher = FileWatcher(path, shared_callback, asyncio.get_event_loop())
            watcher.start()
            self._watchers[path_str] = watcher
            LOGGER.debug(f"Created new watcher for {path_str}")

    def remove_callback(self, path: Path, callback: FileCallback) -> None:
        """Remove a callback for a file path. Removes watcher if no more callbacks."""
        path_str = str(path)
        if path_str not in self._callbacks:
            # May already be removed from stop_all()
            return

        self._callbacks[path_str].discard(callback)

        if not self._callbacks[path_str]:
            # No more callbacks, clean up
            del self._callbacks[path_str]
            if path_str in self._watchers:
                self._watchers[path_str].stop()
                del self._watchers[path_str]
                LOGGER.debug(f"Removed watcher for {path_str}")

    def stop_all(self) -> None:
        """Stop all file watchers."""
        for watcher in self._watchers.values():
            watcher.stop()
        self._watchers.clear()
        self._callbacks.clear()
