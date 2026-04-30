"""Connection tools: list_database_connections, connection_health, connector_capabilities."""

from __future__ import annotations

import httpx

from gateway.governance.context import current_org_id_var
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers, _store_session, mcp_org_id_var
from gateway.mcp.helpers import _format_health_stats
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE
from gateway.mcp_errors import sanitize_proxy_response


@audited_tool(mcp)
async def list_database_connections() -> str:
    """
    List all configured database connections.

    Returns connection names, types, hosts, and status.
    Use the connection name with query_database to run SQL.
    """
    async with _store_session() as store:
        connections = await store.list_connections()
    if not connections:
        return "No database connections configured. Add one via the SignalPilot UI at http://localhost:3200/connections"

    lines = []
    for c in connections:
        lines.append(f"- {c.name} ({c.db_type}) — {c.host}:{c.port}/{c.database}")
        if c.description:
            lines.append(f"  {c.description}")
    return "\n".join(lines)


@audited_tool(mcp)
async def connection_health(connection_name: str = "") -> str:
    """
    Check the health and performance of database connections.

    Returns latency percentiles (p50/p95/p99), error rates, and status
    for monitored connections. Call without arguments to see all connections.

    Args:
        connection_name: Specific connection to check (empty = all connections)

    Returns:
        Health stats as formatted text.
    """
    from gateway.connectors.health_monitor import health_monitor

    org_id = mcp_org_id_var.get(None) or "local"
    token = current_org_id_var.set(org_id)
    try:
        if connection_name:
            stats = health_monitor.connection_stats(connection_name)
            if not stats:
                return f"No health data for '{connection_name}'. Run some queries first."
            return _format_health_stats(stats)

        all_stats = health_monitor.all_stats()
        if not all_stats:
            return "No health data yet. Run some queries to start collecting metrics."

        lines = [f"Connection Health ({len(all_stats)} connections):"]
        for stats in all_stats:
            lines.append("")
            lines.append(_format_health_stats(stats))
        return "\n".join(lines)
    finally:
        current_org_id_var.reset(token)


@audited_tool(mcp)
async def connector_capabilities(connection_name: str = "") -> str:
    """
    Get connector tier classification and available features.

    If connection_name is provided, returns capabilities for that specific connection.
    Otherwise returns the full connector tier matrix.

    Use this to understand what schema metadata is available before querying.
    For example, if a connector doesn't support foreign_keys, you shouldn't
    rely on FK-based join path discovery.
    """
    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=15) as client:
        if connection_name:
            if not _CONN_NAME_RE.match(connection_name):
                return "Error: Invalid connection name"
            r = await client.get(f"{gw}/api/connections/{connection_name}/capabilities", headers=_gw_headers())
        else:
            r = await client.get(f"{gw}/api/connectors/capabilities", headers=_gw_headers())
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    lines = ["Connector Capabilities:"]

    if connection_name:
        lines.append(f"  Connection: {data.get('connection_name', connection_name)}")
        lines.append(f"  DB Type: {data.get('db_type', 'unknown')}")
        lines.append(f"  Tier: {data.get('tier_label', 'unknown')}")
        lines.append(f"  Feature Score: {data.get('feature_score', 0)}%")
        features = data.get("features", {})
        enabled = [k for k, v in features.items() if v]
        disabled = [k for k, v in features.items() if not v]
        if enabled:
            lines.append(f"  Enabled: {', '.join(enabled)}")
        if disabled:
            lines.append(f"  Not Available: {', '.join(disabled)}")
        configured = data.get("configured", {})
        active = [k for k, v in configured.items() if v]
        if active:
            lines.append(f"  Active Config: {', '.join(active)}")
    else:
        for tier_key in ["tier_1", "tier_2", "tier_3"]:
            connectors = data.get(tier_key, [])
            if connectors:
                tier_num = tier_key.split("_")[1]
                lines.append(f"\n  Tier {tier_num}:")
                for c in connectors:
                    lines.append(f"    {c['db_type']}: {c.get('feature_score', 0)}% features")

    return "\n".join(lines)
