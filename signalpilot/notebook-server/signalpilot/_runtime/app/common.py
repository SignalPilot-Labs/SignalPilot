# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import Any

from signalpilot._types.ids import CellId_t

OutputsType = dict[CellId_t, Any]
DefsType = dict[str, Any]

RunOutput = tuple[OutputsType, DefsType]
