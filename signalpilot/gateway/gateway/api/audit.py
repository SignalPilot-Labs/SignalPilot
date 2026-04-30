"""Audit endpoints — GET /api/audit, /api/audit/stats, and /api/audit/export."""

from __future__ import annotations

import json
import os
import time

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func as sa_func

MAX_EXPORT_ROWS = int(os.environ.get("SP_MAX_EXPORT_ROWS", "50000"))

from ..scope_guard import RequireScope
from ..db.models import GatewayAuditLog
from .deps import StoreD

router = APIRouter(prefix="/api")


@router.get("/audit", dependencies=[RequireScope("read")])
async def get_audit(
    store: StoreD,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection_name: str | None = Query(default=None, max_length=64),
    event_type: str | None = Query(default=None, max_length=64),
):
    entries, total = await store.read_audit(
        limit=limit,
        offset=offset,
        connection_name=connection_name,
        event_type=event_type,
        return_total=True,
    )
    return {"entries": entries, "total": total}


@router.get("/audit/stats", dependencies=[RequireScope("read")])
async def get_audit_stats(store: StoreD):
    """Lightweight aggregate stats — single query, no row scanning."""
    from sqlalchemy import case, Integer
    oid = store._require_org_id()
    q = (
        select(
            GatewayAuditLog.event_type,
            sa_func.count().label("cnt"),
            sa_func.sum(case((GatewayAuditLog.blocked == True, 1), else_=0)).label("blocked_cnt"),
        )
        .where(GatewayAuditLog.org_id == oid)
        .group_by(GatewayAuditLog.event_type)
    )
    result = await store.session.execute(q)
    rows = result.all()
    total = 0
    by_type: dict[str, int] = {}
    blocked = 0
    for event_type, cnt, blocked_cnt in rows:
        total += cnt
        by_type[event_type] = cnt
        blocked += blocked_cnt or 0
    return {
        "total": total,
        "mcp_tools": by_type.get("mcp_tool", 0),
        "queries": by_type.get("query", 0),
        "sql": by_type.get("sql", 0),
        "executions": by_type.get("execute", 0),
        "blocked": blocked,
    }


@router.get("/audit/export", dependencies=[RequireScope("admin")])
async def export_audit(
    store: StoreD,
    limit: int | None = Query(default=None, ge=1),
    connection_name: str | None = Query(default=None, max_length=64),
    event_type: str | None = Query(default=None, max_length=64),
    format: str = Query(default="json", pattern=r"^(json|csv)$"),
):
    """Export full audit trail for compliance (Feature #45).

    Returns a downloadable JSON or CSV file with all audit entries
    matching the filter criteria. Suitable for SOC 2, HIPAA, or EU AI Act reporting.
    Capped at SP_MAX_EXPORT_ROWS (default 50 000) to prevent OOM.
    """
    capped_limit = min(limit or MAX_EXPORT_ROWS, MAX_EXPORT_ROWS)
    entries = await store.read_audit(
        limit=capped_limit,
        offset=0,
        connection_name=connection_name,
        event_type=event_type,
    )

    truncated = len(entries) >= capped_limit
    extra_headers: dict[str, str] = {}
    if truncated:
        extra_headers["X-Truncated"] = "true"
        extra_headers["X-Max-Rows"] = str(MAX_EXPORT_ROWS)

    if format == "csv":
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "timestamp", "event_type", "connection_name", "sql",
            "tables", "rows_returned", "duration_ms", "blocked",
            "block_reason", "agent_id", "metadata",
        ])
        for entry in entries:
            e = entry if isinstance(entry, dict) else entry.__dict__
            writer.writerow([
                e.get("id", ""),
                e.get("timestamp", ""),
                e.get("event_type", ""),
                e.get("connection_name", ""),
                e.get("sql", ""),
                ";".join(e.get("tables", [])),
                e.get("rows_returned", ""),
                e.get("duration_ms", ""),
                e.get("blocked", False),
                e.get("block_reason", ""),
                e.get("agent_id", ""),
                json.dumps(e.get("metadata", {})),
            ])
        content = output.getvalue()
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=signalpilot-audit-export.csv", **extra_headers},
        )

    # JSON format
    export_data = {
        "export_timestamp": time.time(),
        "export_format": "signalpilot-audit-v1",
        "filters": {
            "connection_name": connection_name,
            "event_type": event_type,
        },
        "entry_count": len(entries),
        "entries": entries,
    }
    return StreamingResponse(
        iter([json.dumps(export_data, indent=2, default=str)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=signalpilot-audit-export.json", **extra_headers},
    )
