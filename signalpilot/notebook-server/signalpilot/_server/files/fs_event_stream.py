# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import watchdog.events  # type: ignore[import-not-found,import-untyped,unused-ignore]
import watchdog.observers  # type: ignore[import-not-found,import-untyped,unused-ignore]

from signalpilot import _loggers
from signalpilot._server.files.directory_scanner import DirectoryScanner
from signalpilot._server.models.files import FsEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

LOGGER = _loggers.sp_logger()

_COALESCE_INTERVAL_S = 0.150
_RESYNC_THRESHOLD = 500
_HEARTBEAT_INTERVAL_S = 15.0
_SUBSCRIBER_QUEUE_MAX = 1000

_IGNORE_SUFFIXES = (".swp", ".tmp")
_IGNORE_PREFIXES = ("~$",)


def _is_ignored(path_str: str, root: str) -> bool:
    """Return True if this path should be filtered before queuing."""
    if path_str == root:
        return True
    name = Path(path_str).name
    if any(name.endswith(s) for s in _IGNORE_SUFFIXES):
        return True
    if any(name.startswith(p) for p in _IGNORE_PREFIXES):
        return True
    parts = set(Path(path_str).parts)
    return bool(parts & DirectoryScanner.SKIP_DIRS)


class _DirectoryEventHandler(watchdog.events.FileSystemEventHandler):  # type: ignore[misc]
    def __init__(
        self,
        root: str,
        raw_queue: asyncio.Queue[FsEvent],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._root = root
        self._raw_queue = raw_queue
        self._loop = loop

    def _enqueue(self, event: FsEvent) -> None:
        self._loop.call_soon_threadsafe(self._raw_queue.put_nowait, event)

    def _path_str(self, raw: str | bytes) -> str:
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return raw

    def on_created(self, event: watchdog.events.FileSystemEvent) -> None:
        path = self._path_str(event.src_path)
        if _is_ignored(path, self._root):
            return
        self._enqueue(FsEvent(type="created", path=path, is_dir=event.is_directory))

    def on_modified(self, event: watchdog.events.FileSystemEvent) -> None:
        path = self._path_str(event.src_path)
        if _is_ignored(path, self._root):
            return
        self._enqueue(FsEvent(type="modified", path=path, is_dir=event.is_directory))

    def on_deleted(self, event: watchdog.events.FileSystemEvent) -> None:
        path = self._path_str(event.src_path)
        if _is_ignored(path, self._root):
            return
        self._enqueue(FsEvent(type="deleted", path=path, is_dir=event.is_directory))

    def on_moved(self, event: watchdog.events.FileSystemEvent) -> None:
        src = self._path_str(event.src_path)
        dest = self._path_str(event.dest_path)  # type: ignore[attr-defined]
        if _is_ignored(src, self._root) and _is_ignored(dest, self._root):
            return
        self._enqueue(
            FsEvent(
                type="moved",
                path=src,
                dest_path=dest,
                is_dir=event.is_directory,
            )
        )


def _coalesce(events: list[FsEvent]) -> list[FsEvent]:
    """Deduplicate by (type, path), last write wins."""
    seen: dict[tuple[str, str | None], FsEvent] = {}
    for ev in events:
        key = (ev.type, ev.path)
        seen[key] = ev
    return list(seen.values())


class FileSystemEventBroker:
    """Per-process singleton keyed by root directory path.

    # On Linux, inotify watch limit defaults to ~8192 watches. Large workspaces
    # may exhaust this; raise it with:
    #   echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
    """

    _instances: ClassVar[dict[str, FileSystemEventBroker]] = {}

    @classmethod
    def for_root(cls, root: Path) -> FileSystemEventBroker:
        key = str(root)
        if key not in cls._instances:
            cls._instances[key] = cls(root)
        return cls._instances[key]

    @classmethod
    def shutdown_all(cls) -> None:
        for broker in list(cls._instances.values()):
            broker.stop()
        cls._instances.clear()

    def __init__(self, root: Path) -> None:
        self._root = root
        self._observer: object = None  # watchdog.observers.Observer
        self._raw_queue: asyncio.Queue[FsEvent] = asyncio.Queue()
        self._subscribers: list[asyncio.Queue[list[FsEvent]]] = []
        self._coalescer_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._observer is not None:
            return
        loop = asyncio.get_event_loop()
        self._raw_queue = asyncio.Queue()
        handler = _DirectoryEventHandler(
            root=str(self._root),
            raw_queue=self._raw_queue,
            loop=loop,
        )
        observer = watchdog.observers.Observer()
        observer.schedule(handler, str(self._root), recursive=True)  # type: ignore[arg-type]
        observer.start()  # type: ignore[no-untyped-call]
        self._observer = observer
        self._coalescer_task = loop.create_task(self._coalescer())

    def stop(self) -> None:
        if self._coalescer_task is not None:
            self._coalescer_task.cancel()
            self._coalescer_task = None
        if self._observer is not None:
            self._observer.stop()  # type: ignore[attr-defined]
            self._observer.join()  # type: ignore[attr-defined]
            self._observer = None

    def subscribe(self) -> asyncio.Queue[list[FsEvent]]:
        q: asyncio.Queue[list[FsEvent]] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[list[FsEvent]]) -> None:
        self._subscribers = [s for s in self._subscribers if s is not q]

    async def _coalescer(self) -> None:
        while True:
            first = await self._raw_queue.get()
            await asyncio.sleep(_COALESCE_INTERVAL_S)

            batch: list[FsEvent] = [first]
            while not self._raw_queue.empty():
                batch.append(self._raw_queue.get_nowait())

            if len(batch) > _RESYNC_THRESHOLD:
                fanned: list[FsEvent] = [FsEvent(type="resync")]
            else:
                fanned = _coalesce(batch)

            for sub_queue in list(self._subscribers):
                if sub_queue.full():
                    try:
                        sub_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    sub_queue.put_nowait(fanned)
                except asyncio.QueueFull:
                    pass


async def fs_event_generator(
    broker: FileSystemEventBroker,
) -> AsyncIterator[str]:
    """Yield SSE-formatted strings for one subscriber connection."""
    yield "event: message\ndata: {\"type\":\"snapshot\"}\n\n"

    sub_queue = broker.subscribe()
    try:
        while True:
            try:
                batch = await asyncio.wait_for(
                    sub_queue.get(), timeout=_HEARTBEAT_INTERVAL_S
                )
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue

            data = json.dumps(
                {
                    "events": [
                        {
                            "type": ev.type,
                            "path": ev.path,
                            "destPath": ev.dest_path,
                            "isDir": ev.is_dir,
                        }
                        for ev in batch
                    ]
                }
            )
            yield f"event: changes\ndata: {data}\n\n"
    finally:
        broker.unsubscribe(sub_queue)
