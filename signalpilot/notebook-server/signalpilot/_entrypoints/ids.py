# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import Literal

# Internal entrypoints. Not user-facing as the API is not stable.
KnownEntryPoint = Literal[
    "sp.cell.executor",
    "sp.cache.store",
    "sp.kernel.lifespan",
    "sp.server.asgi.lifespan",
    "sp.server.asgi.middleware",
]
