"""MetricProof MCP tools: read warehouse-native semantic layers and verify
agent-built models against them.

Snowflake Semantic Views and Databricks Metric Views are the reference —
"we verify against YOUR semantic layer."
"""

from __future__ import annotations

import json

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MODEL_NAME_RE, _validate_connection_name
from gateway.semantic_layer.conformance import (
    DEFAULT_REL_TOLERANCE,
    compare_metric,
    render_conformance_markdown,
)
from gateway.semantic_layer.providers import provider_for_db_type


async def _connector_ctx(store, connection_name: str):
    conn_info = await store.get_connection(connection_name)
    if conn_info is None:
        available = [c.name for c in await store.list_connections()]
        raise RuntimeError(f"Connection '{connection_name}' not found. Available: {available}")
    conn_str = await store.get_connection_string(connection_name)
    if not conn_str:
        raise RuntimeError("No credentials stored for this connection")
    extras = await store.get_credential_extras(connection_name)
    from gateway.connectors.pool_manager import pool_manager

    return conn_info, pool_manager.connection(
        conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
    )


@audited_tool(mcp)
async def list_semantic_metrics(connection_name: str, schema: str | None = None) -> str:
    """List warehouse-native semantic-layer metrics (Snowflake Semantic Views /
    Databricks Metric Views) available on a connection.

    Use these as the source of truth when building or verifying metric models.
    """
    try:
        if err := _validate_connection_name(connection_name):
            return f"Error: {err}"
        async with _store_session() as store:
            conn_info, ctx = await _connector_ctx(store, connection_name)
        provider = provider_for_db_type(conn_info.db_type)
        if provider is None:
            return (
                f"Error: connection '{connection_name}' is {conn_info.db_type} — semantic-layer "
                "discovery supports snowflake (Semantic Views) and databricks (Metric Views)."
            )

        async with ctx as connector:
            rows = await connector.execute(provider.list_views_sql(schema))
            views = provider.parse_list_views(rows)
            objects = []
            describe_failures = 0
            for view in views[:50]:
                try:
                    desc_rows = await connector.execute(provider.describe_sql(view))
                except Exception:
                    describe_failures += 1
                    continue
                obj = provider.parse_describe(view, desc_rows)
                if obj is not None and (obj.metrics or obj.dimensions):
                    objects.append(obj)

        if not objects:
            suffix = f" ({describe_failures} view(s) could not be described)" if describe_failures else ""
            return (
                f"No semantic-layer objects with metrics found on '{connection_name}'"
                + (f" in schema {schema}" if schema else "")
                + f".{suffix}"
            )
        skipped_note = f" ({describe_failures} view(s) skipped on describe errors)" if describe_failures else ""
        lines = [f"Found {len(objects)} semantic object(s) on '{connection_name}':\n"]
        for obj in objects:
            lines.append(f"  {obj.name} ({obj.kind})")
            for m in obj.metrics[:20]:
                expr = f" = {m.expression}" if m.expression else ""
                lines.append(f"    metric: {m.name}{expr}")
            if obj.dimensions:
                lines.append(f"    dimensions: {', '.join(obj.dimensions[:20])}")
        return "\n".join(lines)

    except Exception as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"


@audited_tool(mcp)
async def verify_metric_conformance(
    connection_name: str,
    semantic_view: str,
    metric: str,
    model_table: str,
    model_metric_column: str,
    dimensions: str = "",
    model_dimension_columns: str = "",
    tolerance_pct: float = 0.5,
) -> str:
    """Verify an agent-built model's metric against the warehouse-native
    semantic layer (Snowflake Semantic View / Databricks Metric View).

    Runs the same metric through both, aligns groups on the dimensions, and
    reports per-group drift. The model table must be aggregated at the
    dimension grain (one row per group); duplicate model groups fail as
    duplicate_in_model. There is deliberately no free-text filter parameter —
    it would be raw SQL through governance; scope with dimensions instead.

    Args:
        connection_name: configured connection (snowflake or databricks)
        semantic_view: qualified semantic/metric view name
        metric: metric name as defined in the semantic layer (Snowflake may
            qualify with the logical table: orders.total_revenue)
        model_table: the agent-built table/view to verify
        model_metric_column: column in model_table holding the metric value
        dimensions: comma-separated semantic-layer dimension names (optional)
        model_dimension_columns: comma-separated model columns matching the
            dimensions, in the same order (defaults to the dimension names)
        tolerance_pct: allowed relative drift percentage (default 0.5; pass 0
            to require exact agreement)
    """
    try:
        if err := _validate_connection_name(connection_name):
            return f"Error: {err}"
        if not model_table or not _MODEL_NAME_RE.match(model_table):
            return f"Error: invalid model_table '{model_table}'"
        dims = [d.strip() for d in dimensions.split(",") if d.strip()]
        model_dims = [d.strip() for d in model_dimension_columns.split(",") if d.strip()] or [
            d.split(".")[-1] for d in dims
        ]
        if len(model_dims) != len(dims):
            return "Error: model_dimension_columns must match dimensions count"

        async with _store_session() as store:
            conn_info, ctx = await _connector_ctx(store, connection_name)
        provider = provider_for_db_type(conn_info.db_type)
        if provider is None:
            return f"Error: '{connection_name}' is {conn_info.db_type}; needs snowflake or databricks"

        ref_sql = provider.reference_query(semantic_view, metrics=[metric], dimensions=dims)

        qc = "`" if conn_info.db_type == "databricks" else '"'

        def q(ident: str) -> str:
            return qc + ident.replace(qc, "") + qc

        model_cols = [q(c) for c in model_dims] + [q(model_metric_column)]
        model_sql = f"SELECT {', '.join(model_cols)} FROM {model_table}"

        async with ctx as connector:
            reference_rows = await connector.execute(ref_sql)
            model_rows = await connector.execute(model_sql)

        # Result columns come back unqualified even when the request used
        # logical-table-qualified names (orders.total_revenue → TOTAL_REVENUE).
        report = compare_metric(
            metric=metric,
            dimensions=dims,
            reference_rows=reference_rows,
            model_rows=model_rows,
            reference_metric_col=metric.split(".")[-1],
            model_metric_col=model_metric_column,
            reference_dim_cols=[d.split(".")[-1] for d in dims],
            model_dim_cols=model_dims,
            tolerance=(tolerance_pct / 100.0) if tolerance_pct is not None else DEFAULT_REL_TOLERANCE,
        )
        md = render_conformance_markdown(report, source_name=semantic_view, model_name=model_table)
        return json.dumps({"summary": report.summary, "report_markdown": md})

    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"
