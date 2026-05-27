# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import Any

from signalpilot._server.ai.tools.base import ToolBase
from signalpilot._server.ai.tools.impl.cells import (
    GetCellOutputs,
    GetCellRuntimeData,
    GetLightweightCellMap,
)
from signalpilot._server.ai.tools.impl.dependency_graph import (
    GetCellDependencyGraph,
)
from signalpilot._server.ai.tools.impl.errors import GetNotebookErrors
from signalpilot._server.ai.tools.impl.lint import LintNotebook
from signalpilot._server.ai.tools.impl.notebooks import GetActiveNotebooks
from signalpilot._server.ai.tools.impl.rules import GetSignalPilotRules
from signalpilot._server.ai.tools.impl.tables_and_variables import (
    GetTablesAndVariables,
)

SUPPORTED_BACKEND_AND_MCP_TOOLS: list[type[ToolBase[Any, Any]]] = [
    GetSignalPilotRules,
    GetActiveNotebooks,
    GetCellRuntimeData,
    GetCellOutputs,
    GetLightweightCellMap,
    GetTablesAndVariables,
    GetNotebookErrors,
    LintNotebook,
    GetCellDependencyGraph,
]
