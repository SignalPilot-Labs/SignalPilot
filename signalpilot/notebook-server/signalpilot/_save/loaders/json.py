from __future__ import annotations

import dataclasses
import json
from typing import Any

from signalpilot._save.cache import Cache
from signalpilot._save.hash import HashKey
from signalpilot._save.loaders.loader import BasePersistenceLoader, LoaderError


class JsonLoader(BasePersistenceLoader):
    """Readable json loader for basic objects."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(name, "json", **kwargs)

    def restore_cache(self, key: HashKey, blob: bytes) -> Cache:
        del key
        cache = json.loads(blob)
        # Handle unserializable stateful_refs
        cache["stateful_refs"] = set(cache["stateful_refs"])
        try:
            hash_key = cache.pop("key", {})
            return Cache(**hash_key, **cache)
        except TypeError as e:
            raise LoaderError(
                "Invalid json object for cache restoration"
            ) from e

    def to_blob(self, cache: Cache) -> bytes:
        dump = dataclasses.asdict(cache)
        dump["stateful_refs"] = list(dump["stateful_refs"])
        return json.dumps(dump, indent=4).encode("utf-8")
