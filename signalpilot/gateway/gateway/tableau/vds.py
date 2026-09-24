"""VizQL Data Service: read a published datasource's fields and query it."""

from __future__ import annotations

from typing import Any

from .client import LONG_TIMEOUT_S, TableauClient, TableauError
from .content import resolve

_VDS = "/api/v1/vizql-data-service"
DEFAULT_QUERY_LIMIT = 500
MAX_QUERY_LIMIT = 5000


async def datasource_fields(client: TableauClient, ref: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(datasource REST object, fields) from VDS read-metadata."""
    ds = await resolve(client, "datasource", ref)
    resp = await client.request(
        "POST",
        f"{_VDS}/read-metadata",
        scope="root",
        json={"datasource": {"datasourceLuid": ds["id"]}},
        headers={"Content-Type": "application/json"},
    )
    fields = [
        {
            "name": f.get("fieldName"),
            "caption": f.get("fieldCaption"),
            "data_type": f.get("dataType"),
            "role": f.get("fieldRole"),
            "default_aggregation": f.get("defaultAggregation"),
        }
        for f in ((resp.json() or {}).get("data") or [])
    ]
    return ds, fields


async def query_datasource(
    client: TableauClient,
    ref: str,
    *,
    fields: list[dict[str, Any]],
    filters: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run a VDS query; rows are cut to ``limit`` (default 500, max 5000)."""
    if not fields:
        raise TableauError("Give at least one field", status_code=400)
    cap = max(1, min(limit or DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT))
    ds = await resolve(client, "datasource", ref)
    query: dict[str, Any] = {"fields": fields}
    if filters:
        query["filters"] = filters
    resp = await client.request(
        "POST",
        f"{_VDS}/query-datasource",
        scope="root",
        json={"datasource": {"datasourceLuid": ds["id"]}, "query": query, "options": {"returnFormat": "OBJECTS"}},
        headers={"Content-Type": "application/json"},
        timeout=LONG_TIMEOUT_S,
    )
    rows = (resp.json() or {}).get("data") or []
    return {"rows": rows[:cap], "row_count": len(rows), "truncated": len(rows) > cap, "datasource_id": ds["id"]}
