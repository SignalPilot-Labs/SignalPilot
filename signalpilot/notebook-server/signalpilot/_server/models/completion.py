# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import Any

import msgspec


class SchemaColumn(msgspec.Struct, rename="camel"):
    name: str
    type: str
    sample_values: list[Any]


class SchemaTable(msgspec.Struct, rename="camel"):
    name: str
    columns: list[SchemaColumn]


class VariableContext(msgspec.Struct, rename="camel"):
    name: str
    value_type: str
    preview_value: Any
