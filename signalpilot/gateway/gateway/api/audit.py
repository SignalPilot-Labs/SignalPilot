"""Audit endpoints — GET /api/audit and GET /api/audit/export."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from .deps import StoreD

router = APIRouter(prefix="/api")


@router.get("/audit")
async def get_audit(
    store: StoreD,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
    connection_name: str | None = None,
    event_type: str | None = None,
):
    entries = await store.read_audit(
        limit=limit,
        offset=offset,
        connection_name=connection_name,
        event_type=event_type,
    )
    return {"entries": entries, "total": len(entries)}


@router.get("/audit/export")
async def export_audit(
    store: StoreD,
    connection_name: str | None = None,
    event_type: str | None = None,
    format: str = Query(default="json", pattern=r"^(json|csv)$"),
):
    """Export full audit trail for compliance (Feature #45).

    Returns a downloadable JSON or CSV file with all audit entries
    matching the filter criteria. Suitable for SOC 2, HIPAA, or EU AI Act reporting.
    """
    entries = await store.read_audit(
        limit=10_000,
        offset=0,
        connection_name=connection_name,
        event_type=event_type,
    )

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
            headers={"Content-Disposition": "attachment; filename=signalpilot-audit-export.csv"},
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
        headers={"Content-Disposition": "attachment; filename=signalpilot-audit-export.json"},
    )
