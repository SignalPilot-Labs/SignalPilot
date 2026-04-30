from __future__ import annotations

from fastapi import HTTPException, Query

from gateway.api.connections._router import router
from gateway.auth import OrgID, UserID
from gateway.connectors.health_monitor import health_monitor
from gateway.scope_guard import RequireScope


@router.get("/connections/health", dependencies=[RequireScope("read")])
async def get_all_connection_health(_: UserID, _org: OrgID, window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for all monitored connections."""
    return {"connections": health_monitor.all_stats(window)}


@router.get("/connections/{name}/health", dependencies=[RequireScope("read")])
async def get_connection_health(_: UserID, _org: OrgID, name: str, window: int = Query(default=300, ge=60, le=3600)):
    """Get health stats for a specific connection."""
    stats = health_monitor.connection_stats(name, window)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"No health data for connection '{name}'")
    return stats


@router.get("/connections/{name}/health/history", dependencies=[RequireScope("read")])
async def get_connection_health_history(
    _: UserID,
    _org: OrgID,
    name: str,
    window: int = Query(default=3600, ge=300, le=86400, description="History window in seconds"),
    bucket: int = Query(default=60, ge=10, le=3600, description="Bucket size in seconds"),
):
    """Get time-bucketed health history for sparkline/chart rendering."""
    history = health_monitor.connection_history(name, window, bucket)
    if history is None:
        raise HTTPException(status_code=404, detail=f"No health data for connection '{name}'")
    return {
        "connection_name": name,
        "window_seconds": window,
        "bucket_seconds": bucket,
        "buckets": history,
    }
