from __future__ import annotations

from typing import Literal

from signalpilot._save.loaders.json import JsonLoader
from signalpilot._save.loaders.lazy import LazyLoader
from signalpilot._save.loaders.loader import (
    BasePersistenceLoader,
    Loader,
    LoaderPartial,
    LoaderType,
)
from signalpilot._save.loaders.memory import MemoryLoader
from signalpilot._save.loaders.pickle import PickleLoader

LoaderKey = Literal["memory", "pickle", "json", "lazy"]

PERSISTENT_LOADERS: dict[LoaderKey, LoaderType] = {
    "pickle": PickleLoader,
    "json": JsonLoader,
    "lazy": LazyLoader,
}

__all__ = [
    "PERSISTENT_LOADERS",
    "BasePersistenceLoader",
    "JsonLoader",
    "LazyLoader",
    "Loader",
    "LoaderKey",
    "LoaderPartial",
    "LoaderType",
    "MemoryLoader",
    "PickleLoader",
]
