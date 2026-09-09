"""Dashboard file tools for the standalone chat agent.

A dashboard is ``artifacts/<name>.dashboard.json`` validated by the schema
in the agent plugin (``skills/dashboard/dashboard.schema.json``). A SQL
dataset reads its snapshot at ``artifacts/datasets/<name>.csv``.
"""

from __future__ import annotations

from signalpilot._server.ai.dashboard.datasets import (
    LoadedDataset,
    load_dataset,
    load_datasets,
    parse_csv,
    resolve_scratch_path,
)
from signalpilot._server.ai.dashboard.prepare import (
    FAILED_CODES,
    chart_is_failed,
    infer_column_types,
    prepare_chart_rows,
)
from signalpilot._server.ai.dashboard.published import (
    list_published,
    load_published,
)
from signalpilot._server.ai.dashboard.schema import (
    DashboardSchemaUnavailable,
    dataset_file_refs,
    dataset_sql,
    locate_schema_file,
    snapshot_path,
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
    "dataset_file_refs",
    "dataset_sql",
    "infer_column_types",
    "list_published",
    "load_dataset",
    "load_datasets",
    "load_published",
    "locate_schema_file",
    "parse_csv",
    "prepare_chart_rows",
    "resolve_scratch_path",
    "snapshot_path",
    "validate_spec",
]
