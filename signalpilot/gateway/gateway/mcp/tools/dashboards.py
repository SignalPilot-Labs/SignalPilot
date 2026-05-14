"""Dashboard management tools: create, list, get, add/update/remove charts."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from gateway.mcp.audit import audited_tool
from gateway.mcp.server import mcp

_VALID_CHART_TYPES = {
    "bar", "line", "area", "scatter", "pie", "histogram",
    "radar", "gauge", "funnel", "heatmap", "treemap", "sunburst",
    "sankey", "boxplot", "candlestick", "graph",
    "table", "kpi",
}

_UUID_RE_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
import re

_UUID_RE = re.compile(_UUID_RE_PATTERN, re.IGNORECASE)


def _dashboards_dir() -> Path:
    d = Path(os.environ.get("SP_DASHBOARDS_DIR", "/tmp/sp-workspaces/dashboards"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_dashboard(dashboard_id: str) -> dict | None:
    if not _UUID_RE.match(dashboard_id):
        return None
    path = _dashboards_dir() / f"{dashboard_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_dashboard(dashboard: dict) -> None:
    path = _dashboards_dir() / f"{dashboard['id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dashboard, indent=2, default=str), encoding="utf-8")
    tmp.rename(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _execute_chart_sql(
    connection_name: str, sql: str, row_limit: int = 200
) -> dict | None:
    """Execute SQL via the gateway query pipeline and return cached data structure."""
    from gateway.engine import inject_limit
    from gateway.engine import validate_sql as engine_validate_sql
    from gateway.mcp.context import _store_session
    from gateway.mcp.validation import _validate_connection_name, _validate_sql
    from gateway.connectors.pool_manager import pool_manager

    if _validate_connection_name(connection_name):
        return None
    if _validate_sql(sql):
        return None

    validation = engine_validate_sql(sql)
    if not validation.ok:
        return None

    row_limit = min(row_limit, 500)
    try:
        safe_sql = inject_limit(sql, row_limit)
    except ValueError:
        return None

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            return None
        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return None
        extras = await store.get_credential_extras(connection_name)

        try:
            async with pool_manager.connection(
                conn_info.db_type,
                conn_str,
                credential_extras=extras,
                connection_name=connection_name,
            ) as connector:
                rows = await connector.execute(safe_sql)
        except Exception:
            return None

    if not rows:
        return {
            "columns": [],
            "rows": [],
            "computedAt": _now_iso(),
        }

    columns = [{"name": c, "type": "text"} for c in rows[0].keys()]
    data_rows = [[row.get(c["name"]) for c in columns] for row in rows]
    return {
        "columns": columns,
        "rows": data_rows,
        "computedAt": _now_iso(),
    }


@audited_tool(mcp)
async def create_dashboard(name: str, description: str = "") -> str:
    """
    Create a new empty dashboard.

    Args:
        name: Dashboard name (1-120 characters)
        description: Optional description (max 500 characters)

    Returns:
        Dashboard ID and confirmation.
    """
    name = name.strip()
    if not name or len(name) > 120:
        return "Error: Name must be between 1 and 120 characters."
    description = description.strip()
    if len(description) > 500:
        return "Error: Description must be under 500 characters."

    dashboard_id = str(uuid.uuid4())
    now = _now_iso()
    dashboard = {
        "schemaVersion": 1,
        "id": dashboard_id,
        "name": name,
        "description": description,
        "layout": {"columns": 12, "rowHeight": 80},
        "charts": [],
        "createdAt": now,
        "updatedAt": now,
    }
    _save_dashboard(dashboard)
    return f"Dashboard created: {dashboard_id}\nName: {name}"


@audited_tool(mcp)
async def list_dashboards() -> str:
    """
    List all dashboards.

    Returns:
        Dashboard names, IDs, chart counts, and last updated timestamps.
    """
    d = _dashboards_dir()
    files = sorted(d.glob("*.json"))
    if not files:
        return "No dashboards found. Use create_dashboard to create one."

    dashboards = []
    for f in files:
        if f.name.endswith(".json.tmp"):
            continue
        try:
            data = json.loads(f.read_text("utf-8"))
            dashboards.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    dashboards.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)

    lines = [f"Found {len(dashboards)} dashboard(s):\n"]
    for db in dashboards:
        chart_count = len(db.get("charts", []))
        lines.append(
            f"  - {db['name']} (id: {db['id']}, {chart_count} chart(s), updated: {db.get('updatedAt', 'unknown')})"
        )
    return "\n".join(lines)


@audited_tool(mcp)
async def get_dashboard(dashboard_id: str) -> str:
    """
    Get the full state of a dashboard including all its charts.

    Args:
        dashboard_id: UUID of the dashboard

    Returns:
        Dashboard metadata, layout, and details of every chart (title, type, SQL, position).
    """
    db = _load_dashboard(dashboard_id)
    if not db:
        return f"Error: Dashboard '{dashboard_id}' not found."

    lines = [
        f"Dashboard: {db['name']}",
        f"ID: {db['id']}",
        f"Description: {db.get('description', '')}",
        f"Layout: {db.get('layout', {}).get('columns', 12)} columns",
        f"Created: {db.get('createdAt', 'unknown')}",
        f"Updated: {db.get('updatedAt', 'unknown')}",
        f"Charts: {len(db.get('charts', []))}",
    ]

    for i, chart in enumerate(db.get("charts", []), 1):
        pos = chart.get("position", {})
        has_data = "cachedData" in chart and chart["cachedData"] is not None
        lines.append(f"\n  Chart {i}: {chart.get('title', 'Untitled')}")
        lines.append(f"    ID: {chart['id']}")
        lines.append(f"    Type: {chart.get('chartType', 'unknown')}")
        lines.append(f"    Connection: {chart.get('connectionName', 'unknown')}")
        lines.append(f"    SQL: {chart.get('sql', '')[:200]}")
        lines.append(
            f"    Position: x={pos.get('x', 0)} y={pos.get('y', 0)} w={pos.get('w', 6)} h={pos.get('h', 4)}"
        )
        lines.append(f"    Has cached data: {has_data}")
        if has_data:
            cached = chart["cachedData"]
            lines.append(f"    Cached rows: {len(cached.get('rows', []))}")
            lines.append(f"    Computed at: {cached.get('computedAt', 'unknown')}")

    return "\n".join(lines)


@audited_tool(mcp)
async def add_chart_to_dashboard(
    dashboard_id: str,
    title: str,
    chart_type: str,
    sql: str,
    connection_name: str,
    echarts_option: str = "{}",
    position_x: int = 0,
    position_y: int = 0,
    position_w: int = 6,
    position_h: int = 4,
) -> str:
    """
    Add a chart to an existing dashboard. Executes the SQL to cache results for display.

    Use query_database first to validate your SQL before adding it to a dashboard.

    Supported chart_type values: bar, line, area, scatter, pie, histogram,
    radar, gauge, funnel, heatmap, treemap, sunburst, sankey, boxplot,
    candlestick, graph, table, kpi

    Convention for SQL result shape:
    - bar/line/area: first column = x-axis (categories/dates), remaining columns = y-axis series
    - scatter: first column = x values, second column = y values
    - pie: first column = name/label, second column = value
    - histogram: first column = values to bin (auto-binned by the renderer)
    - radar: first column = indicator names, remaining columns = series values
    - gauge: first row, first column = the number to display (like kpi but rendered as a gauge dial)
    - funnel: first column = stage name, second column = value (rendered largest-to-smallest)
    - heatmap: first column = x category, second column = y category, third column = value
    - treemap: first column = name, second column = value (area-proportional rectangles)
    - sunburst: first column = name, second column = value (nested ring chart)
    - sankey: first column = source, second column = target, third column = flow value
    - boxplot: first column = category/group, second column = numeric value (many rows per category, stats computed automatically)
    - candlestick: first column = date, then open, close, low, high columns
    - graph: first column = source node, second column = target node, optional third column = value
    - table: all columns rendered as-is
    - kpi: first row, first column = the number to display

    Position uses a 12-column grid. x=column (0-11), y=row, w=width (1-12), h=height in grid units.

    Args:
        dashboard_id: UUID of the target dashboard
        title: Chart title (1-120 characters)
        chart_type: One of: bar, line, area, scatter, pie, histogram, radar, gauge, funnel, heatmap, treemap, sunburst, sankey, boxplot, candlestick, graph, table, kpi
        sql: SQL query (SELECT only, max 4000 characters)
        connection_name: Database connection to execute against
        echarts_option: JSON string of ECharts option overrides (optional)
        position_x: Grid column position (0-11, default 0)
        position_y: Grid row position (default 0)
        position_w: Grid width in columns (1-12, default 6)
        position_h: Grid height in row units (default 4)

    Returns:
        Chart ID and confirmation, including whether data was cached.
    """
    db = _load_dashboard(dashboard_id)
    if not db:
        return f"Error: Dashboard '{dashboard_id}' not found."

    title = title.strip()
    if not title or len(title) > 120:
        return "Error: Title must be between 1 and 120 characters."

    if chart_type not in _VALID_CHART_TYPES:
        return f"Error: Invalid chart_type '{chart_type}'. Must be one of: {', '.join(sorted(_VALID_CHART_TYPES))}"

    sql = sql.strip()
    if not sql or len(sql) > 4000:
        return "Error: SQL must be between 1 and 4000 characters."

    try:
        option_dict = json.loads(echarts_option)
        if not isinstance(option_dict, dict):
            return "Error: echarts_option must be a JSON object."
    except json.JSONDecodeError as e:
        return f"Error: Invalid echarts_option JSON: {e}"

    position_w = max(1, min(12, position_w))
    position_x = max(0, min(11, position_x))
    position_h = max(1, position_h)
    position_y = max(0, position_y)

    chart_id = str(uuid.uuid4())

    cached_data = await _execute_chart_sql(connection_name, sql)

    chart = {
        "id": chart_id,
        "title": title,
        "chartType": chart_type,
        "sql": sql,
        "connectionName": connection_name,
        "echartsOption": option_dict,
        "position": {"x": position_x, "y": position_y, "w": position_w, "h": position_h},
    }
    if cached_data:
        chart["cachedData"] = cached_data

    db["charts"].append(chart)
    db["updatedAt"] = _now_iso()
    _save_dashboard(db)

    data_msg = (
        f"Data cached ({len(cached_data['rows'])} rows)"
        if cached_data
        else "No cached data (SQL execution failed or no connection available)"
    )
    return f"Chart added: {chart_id}\nTitle: {title}\nType: {chart_type}\n{data_msg}"


@audited_tool(mcp)
async def update_chart(
    dashboard_id: str,
    chart_id: str,
    title: str | None = None,
    chart_type: str | None = None,
    sql: str | None = None,
    connection_name: str | None = None,
    echarts_option: str | None = None,
    position_x: int | None = None,
    position_y: int | None = None,
    position_w: int | None = None,
    position_h: int | None = None,
) -> str:
    """
    Update an existing chart on a dashboard. Only provided fields are changed.

    If SQL or connection_name changes, the chart data is re-executed and cached.

    Args:
        dashboard_id: UUID of the dashboard
        chart_id: UUID of the chart to update
        title: New title (optional)
        chart_type: New chart type (optional)
        sql: New SQL query (optional)
        connection_name: New database connection (optional)
        echarts_option: New ECharts option overrides as JSON string (optional)
        position_x: New grid column position (optional)
        position_y: New grid row position (optional)
        position_w: New grid width (optional)
        position_h: New grid height (optional)

    Returns:
        Confirmation with updated fields.
    """
    db = _load_dashboard(dashboard_id)
    if not db:
        return f"Error: Dashboard '{dashboard_id}' not found."

    chart = next((c for c in db.get("charts", []) if c["id"] == chart_id), None)
    if not chart:
        return f"Error: Chart '{chart_id}' not found in dashboard '{dashboard_id}'."

    updated_fields = []
    re_execute = False

    if title is not None:
        title = title.strip()
        if not title or len(title) > 120:
            return "Error: Title must be between 1 and 120 characters."
        chart["title"] = title
        updated_fields.append("title")

    if chart_type is not None:
        if chart_type not in _VALID_CHART_TYPES:
            return f"Error: Invalid chart_type '{chart_type}'."
        chart["chartType"] = chart_type
        updated_fields.append("chartType")

    if sql is not None:
        sql = sql.strip()
        if not sql or len(sql) > 4000:
            return "Error: SQL must be between 1 and 4000 characters."
        chart["sql"] = sql
        updated_fields.append("sql")
        re_execute = True

    if connection_name is not None:
        chart["connectionName"] = connection_name
        updated_fields.append("connectionName")
        re_execute = True

    if echarts_option is not None:
        try:
            option_dict = json.loads(echarts_option)
            if not isinstance(option_dict, dict):
                return "Error: echarts_option must be a JSON object."
            chart["echartsOption"] = option_dict
            updated_fields.append("echartsOption")
        except json.JSONDecodeError as e:
            return f"Error: Invalid echarts_option JSON: {e}"

    pos = chart.get("position", {"x": 0, "y": 0, "w": 6, "h": 4})
    if position_x is not None:
        pos["x"] = max(0, min(11, position_x))
        updated_fields.append("position_x")
    if position_y is not None:
        pos["y"] = max(0, position_y)
        updated_fields.append("position_y")
    if position_w is not None:
        pos["w"] = max(1, min(12, position_w))
        updated_fields.append("position_w")
    if position_h is not None:
        pos["h"] = max(1, position_h)
        updated_fields.append("position_h")
    chart["position"] = pos

    if re_execute:
        cached_data = await _execute_chart_sql(chart["connectionName"], chart["sql"])
        if cached_data:
            chart["cachedData"] = cached_data

    if not updated_fields:
        return "No fields to update."

    db["updatedAt"] = _now_iso()
    _save_dashboard(db)
    return f"Chart '{chart_id}' updated: {', '.join(updated_fields)}"


@audited_tool(mcp)
async def remove_chart_from_dashboard(dashboard_id: str, chart_id: str) -> str:
    """
    Remove a chart from a dashboard.

    Args:
        dashboard_id: UUID of the dashboard
        chart_id: UUID of the chart to remove

    Returns:
        Confirmation message.
    """
    db = _load_dashboard(dashboard_id)
    if not db:
        return f"Error: Dashboard '{dashboard_id}' not found."

    original_count = len(db.get("charts", []))
    db["charts"] = [c for c in db.get("charts", []) if c["id"] != chart_id]

    if len(db["charts"]) == original_count:
        return f"Error: Chart '{chart_id}' not found in dashboard '{dashboard_id}'."

    db["updatedAt"] = _now_iso()
    _save_dashboard(db)
    return f"Chart '{chart_id}' removed from dashboard '{dashboard_id}'."


@audited_tool(mcp)
async def delete_dashboard(dashboard_id: str) -> str:
    """
    Delete an entire dashboard and all its charts.

    Args:
        dashboard_id: UUID of the dashboard to delete

    Returns:
        Confirmation message.
    """
    if not _UUID_RE.match(dashboard_id):
        return f"Error: Invalid dashboard ID '{dashboard_id}'."

    path = _dashboards_dir() / f"{dashboard_id}.json"
    if not path.exists():
        return f"Error: Dashboard '{dashboard_id}' not found."

    path.unlink()
    return f"Dashboard '{dashboard_id}' deleted."
