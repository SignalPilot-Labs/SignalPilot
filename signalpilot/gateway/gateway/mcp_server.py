"""
SignalPilot MCP Server — thin shim re-exporting every public name.

The real implementation lives in gateway/mcp/. This module keeps all
existing import paths (tests, entry point) working without change.

Entry point: signalpilot-mcp = "gateway.mcp_server:main"
"""

from __future__ import annotations

# Trigger tool registration (all @audited_tool(mcp) decorators run at import time).
import gateway.mcp  # noqa: F401
from gateway.db.engine import get_session_factory
from gateway.dbt import (
    format_validation_result as _format_validation_result,
)
from gateway.dbt import (
    validate_project as _validate_project,
)
from gateway.mcp.context import (
    _gateway_url,
    _gw_headers,
    _is_cloud,
    _store_session,
    mcp_audit_id_var,
    mcp_client_ip_var,
    mcp_org_id_var,
    mcp_raw_key_var,
    mcp_user_agent_var,
    mcp_user_id_var,
)
from gateway.mcp.server import main, mcp
from gateway.mcp.tools.connections import (
    connection_health,
    connector_capabilities,
    list_database_connections,
)
from gateway.mcp.tools.dbt_fixers import fix_date_spine_hazards, fix_nondeterminism_hazards
from gateway.mcp.tools.dbt_project import (
    dbt_error_parser,
    dbt_project_map,
    dbt_project_validate,
    generate_sql_skeleton,
)
from gateway.mcp.tools.model_verify import (
    analyze_grain,
    audit_model_sources,
    check_model_schema,
    compare_join_types,
    validate_model_output,
)
from gateway.mcp.tools.projects import create_project, get_project, list_projects
from gateway.mcp.tools.query import (
    check_budget,
    debug_cte_query,
    estimate_query_cost,
    explain_query,
    query_database,
    query_history,
    validate_sql,
)
from gateway.mcp.tools.sandbox import execute_code, sandbox_status
from gateway.mcp.tools.schema import (
    describe_table,
    explore_column,
    explore_columns,
    explore_table,
    find_join_path,
    get_date_boundaries,
    get_relationships,
    list_tables,
    schema_ddl,
    schema_diff,
    schema_link,
    schema_overview,
    schema_statistics,
)
from gateway.mcp.validation import _quote_table
from gateway.store import Store

__all__ = [
    # FastMCP instance + entry point
    "mcp",
    "main",
    # Context variables
    "mcp_user_id_var",
    "mcp_org_id_var",
    "mcp_raw_key_var",
    "mcp_audit_id_var",
    "mcp_client_ip_var",
    "mcp_user_agent_var",
    # Session helper
    "_store_session",
    # Validation helper used by tests
    "_quote_table",
    # dbt helpers patched in tests
    "_validate_project",
    "_format_validation_result",
    # DB helpers patched in tests (without create=True)
    "get_session_factory",
    "Store",
    # Tool functions
    "query_database",
    "list_database_connections",
    "describe_table",
    "list_tables",
    "get_date_boundaries",
    "check_budget",
    "connection_health",
    "find_join_path",
    "get_relationships",
    "explore_table",
    "schema_overview",
    "connector_capabilities",
    "schema_diff",
    "schema_ddl",
    "schema_link",
    "explain_query",
    "validate_sql",
    "query_history",
    "explore_columns",
    "schema_statistics",
    "explore_column",
    "estimate_query_cost",
    "debug_cte_query",
    "check_model_schema",
    "dbt_error_parser",
    "generate_sql_skeleton",
    "analyze_grain",
    "validate_model_output",
    "audit_model_sources",
    "compare_join_types",
    "dbt_project_map",
    "dbt_project_validate",
    "create_project",
    "list_projects",
    "get_project",
    "fix_date_spine_hazards",
    "fix_nondeterminism_hazards",
    "execute_code",
    "sandbox_status",
]

if __name__ == "__main__":
    main()
