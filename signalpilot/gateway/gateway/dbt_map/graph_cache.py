"""Process-local LRU of decoded dbt graphs and their derived payloads.

A graph_key names one immutable compiled revision, so cached entries never
go stale; LRU eviction (entry count plus a rough byte budget) is the only
invalidation. Everything lives on the single asyncio loop; the fill lock
stops concurrent first requests from each fetching and decoding the same
graph. Misses and errors are never cached.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import sys
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from .slices import build_cone, build_skeleton

MAX_ENTRIES = 8
BYTE_BUDGET = 64 * 1024 * 1024
MAX_CONES_PER_GRAPH = 256
MAX_ENVELOPES_PER_GRAPH = 8
MAX_SQL_MAPS = 2
SQL_BYTE_BUDGET = 32 * 1024 * 1024
GZIP_LEVEL = 6
# Decoded dicts cost several times their JSON size; count them roughly.
_DICT_FACTOR = 3

Loader = Callable[[], Awaitable[bytes | None]]
Extractor = Callable[[bytes], dict]


class GraphEntry:
    """One decoded graph plus lazily built variants."""

    def __init__(self, graph_key: str, graph: dict, raw: bytes) -> None:
        self.graph_key = graph_key
        self.graph = graph
        self.raw = raw
        self._skeleton: dict | None = None
        self._skeleton_raw: bytes | None = None
        self._envelopes: OrderedDict[tuple[str, str], tuple[bytes, bytes]] = OrderedDict()
        self._cones: OrderedDict[tuple[str, int | None], dict] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def approx_bytes(self) -> int:
        total = len(self.raw) * _DICT_FACTOR
        if self._skeleton_raw is not None:
            total += len(self._skeleton_raw) * _DICT_FACTOR
        for body, gz in self._envelopes.values():
            total += len(body) + len(gz)
        total += sum(sys.getsizeof(c) for c in self._cones.values())
        return total

    def skeleton(self) -> dict:
        if self._skeleton is None:
            self._skeleton = build_skeleton(self.graph)
        return self._skeleton

    def skeleton_raw(self) -> bytes:
        if self._skeleton_raw is None:
            self._skeleton_raw = json.dumps(self.skeleton(), separators=(",", ":")).encode("utf-8")
        return self._skeleton_raw

    def variant_raw(self, variant: str) -> bytes:
        if variant == "skeleton":
            return self.skeleton_raw()
        return self.raw

    async def envelope(self, variant: str, etag: str, prefix: bytes) -> tuple[bytes, bytes]:
        """(identity, gzip) bytes of `prefix + graph json + "}"`, built once."""
        key = (variant, etag)
        hit = self._envelopes.get(key)
        if hit is not None:
            self._envelopes.move_to_end(key)
            return hit
        async with self._lock:
            hit = self._envelopes.get(key)
            if hit is not None:
                return hit
            body = prefix + self.variant_raw(variant) + b"}"
            gz = await asyncio.to_thread(gzip.compress, body, GZIP_LEVEL)
            self._envelopes[key] = (body, gz)
            while len(self._envelopes) > MAX_ENVELOPES_PER_GRAPH:
                self._envelopes.popitem(last=False)
            return body, gz

    def cone(self, uid: str, hops: int | None) -> dict:
        key = (uid, hops)
        hit = self._cones.get(key)
        if hit is not None:
            self._cones.move_to_end(key)
            return hit
        result = build_cone(self.graph, uid, hops)
        self._cones[key] = result
        while len(self._cones) > MAX_CONES_PER_GRAPH:
            self._cones.popitem(last=False)
        return result


class GraphCache:
    def __init__(self, max_entries: int = MAX_ENTRIES, byte_budget: int = BYTE_BUDGET) -> None:
        self.max_entries = max_entries
        self.byte_budget = byte_budget
        self._entries: OrderedDict[str, GraphEntry] = OrderedDict()
        self._fills: dict[str, asyncio.Lock] = {}
        self.hits = 0
        self.misses = 0

    def get(self, graph_key: str) -> GraphEntry | None:
        entry = self._entries.get(graph_key)
        if entry is not None:
            self._entries.move_to_end(graph_key)
            self.hits += 1
        return entry

    async def get_or_load(self, graph_key: str, loader: Loader) -> GraphEntry | None:
        """Return the entry, filling from `loader` (gzipped graph bytes) on a miss."""
        entry = self.get(graph_key)
        if entry is not None:
            return entry
        lock = self._fills.setdefault(graph_key, asyncio.Lock())
        async with lock:
            entry = self._entries.get(graph_key)
            if entry is not None:
                return entry
            self.misses += 1
            data = await loader()
            if data is None:
                return None
            raw = await asyncio.to_thread(gzip.decompress, data)
            graph = await asyncio.to_thread(json.loads, raw)
            entry = GraphEntry(graph_key, graph, raw)
            self._entries[graph_key] = entry
            self._evict()
        if len(self._fills) > 64:
            self._fills = {k: v for k, v in self._fills.items() if v.locked()}
        return entry

    def _evict(self) -> None:
        while len(self._entries) > 1 and (
            len(self._entries) > self.max_entries
            or sum(e.approx_bytes for e in self._entries.values()) > self.byte_budget
        ):
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
        self._fills.clear()
        self.hits = self.misses = 0

    def stats(self) -> dict[str, Any]:
        return {
            "entries": len(self._entries),
            "approx_bytes": sum(e.approx_bytes for e in self._entries.values()),
            "hits": self.hits,
            "misses": self.misses,
        }


class SqlMapCache:
    """LRU of extracted SQL maps keyed by sql_key or manifest_key.

    Only the small extracted dict is kept, never a decoded manifest. Each
    entry also memoizes the per-node response payloads it has served.
    """

    def __init__(self, max_entries: int = MAX_SQL_MAPS, byte_budget: int = SQL_BYTE_BUDGET) -> None:
        self.max_entries = max_entries
        self.byte_budget = byte_budget
        self._entries: OrderedDict[str, tuple[dict, int, OrderedDict[str, dict]]] = OrderedDict()
        self._fills: dict[str, asyncio.Lock] = {}
        self.loads = 0

    def get(self, key: str) -> dict | None:
        hit = self._entries.get(key)
        if hit is None:
            return None
        self._entries.move_to_end(key)
        return hit[0]

    async def get_or_load(self, key: str, loader: Loader, extractor: Extractor) -> dict | None:
        """`loader` returns gzipped bytes; `extractor` turns the gunzipped bytes into the map."""
        hit = self.get(key)
        if hit is not None:
            return hit
        lock = self._fills.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self.get(key)
            if hit is not None:
                return hit
            data = await loader()
            if data is None:
                return None
            self.loads += 1
            raw = await asyncio.to_thread(gzip.decompress, data)
            sql_map = await asyncio.to_thread(extractor, raw)
            size = sum(len(v.get("raw") or "") + len(v.get("compiled") or "") for v in sql_map.values())
            self._entries[key] = (sql_map, size * _DICT_FACTOR, OrderedDict())
            while len(self._entries) > 1 and (
                len(self._entries) > self.max_entries
                or sum(e[1] for e in self._entries.values()) > self.byte_budget
            ):
                self._entries.popitem(last=False)
        if len(self._fills) > 64:
            self._fills = {k: v for k, v in self._fills.items() if v.locked()}
        return sql_map

    def payload(self, key: str, uid: str, builder: Callable[[], dict]) -> dict:
        """Per-(key, uid) memo of the built response body."""
        entry = self._entries.get(key)
        if entry is None:
            return builder()
        memo = entry[2]
        hit = memo.get(uid)
        if hit is None:
            hit = memo[uid] = builder()
            while len(memo) > MAX_CONES_PER_GRAPH:
                memo.popitem(last=False)
        return hit

    def clear(self) -> None:
        self._entries.clear()
        self._fills.clear()
        self.loads = 0

    def stats(self) -> dict[str, Any]:
        return {"entries": len(self._entries), "loads": self.loads}


graph_cache = GraphCache()
sql_map_cache = SqlMapCache()
