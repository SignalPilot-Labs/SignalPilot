"""Dashboard file tools for the standalone chat agent.

A dashboard is ``artifacts/<name>.dashboard.json`` validated by the schema
in the agent plugin (``skills/dashboard/dashboard.schema.json``).
"""

from __future__ import annotations

from signalpilot._server.ai.dashboard.datasets import (
    LoadedDataset,
    load_dataset,
    load_datasets,
    parse_dataset_text,
    resolve_scratch_path,
)
from signalpilot._server.ai.dashboard.prepare import (
    FAILED_CODES,
    chart_is_failed,
    infer_column_types,
    prepare_chart_rows,
)
from signalpilot._server.ai.dashboard.schema import (
    DashboardSchemaUnavailable,
    load_schema,
    locate_schema_file,
    validate_spec,
)
from signalpilot._server.ai.dashboard.tools import (
    dashboard_sample_data,
    dashboard_screenshot,
)

__all__ = [
    "FAILED_CODES",
    "DashboardSchemaUnavailable",
    "LoadedDataset",
    "chart_is_failed",
    "dashboard_sample_data",
    "dashboard_screenshot",
    "infer_column_types",
    "load_dataset",
    "load_datasets",
    "load_schema",
    "locate_schema_file",
    "parse_dataset_text",
    "prepare_chart_rows",
    "resolve_scratch_path",
    "validate_spec",
]
