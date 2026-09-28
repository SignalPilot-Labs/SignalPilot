"""Tableau runtime routes for chat runs: search, read, query, render.

Refs are a Tableau id or an exact name. Routes use ``{ref:path}`` so a name
that contains ``/`` (sent as ``%2F``) still resolves; the more specific
``.../content``, ``.../fields``, ``.../image``, ``.../data`` routes are
registered before the bare ones.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ...security.scope_guard import RequireScope
from ...tableau import content as tableau_content
from ...tableau import vds as tableau_vds
from ...tableau.client import TableauClient
from ...tableau.connections import connection_target
from ..deps import StoreD
from .common import run_tableau

router = APIRouter(prefix="/api/tableau/runtime")

SearchKind = Literal["all", "workbook", "view", "datasource", "project"]


class DatasourceQueryBody(BaseModel):
    fields: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    filters: list[dict[str, Any]] | None = Field(default=None, max_length=200)
    limit: int | None = Field(default=None, ge=1, le=tableau_vds.MAX_QUERY_LIMIT)


@router.get("/search", dependencies=[RequireScope("execute")])
async def tableau_search(
    request: Request,
    store: StoreD,
    q: str = Query(default="", max_length=500),
    kind: SearchKind = "all",
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    async def op(client: TableauClient) -> dict[str, Any]:
        return {"results": await tableau_content.search(client, q, kind, limit)}

    return await run_tableau(request, store, "search", f"{kind}:{q}", op)


@router.get("/workbooks/{ref:path}/content", dependencies=[RequireScope("execute")])
async def tableau_workbook_content(ref: str, request: Request, store: StoreD) -> Response:
    """Raw ``.twb`` XML (extracted from a ``.twbx`` when needed)."""

    async def op(client: TableauClient) -> tuple[dict[str, Any], bytes]:
        return await tableau_content.download_workbook(client, ref)

    workbook, data = await run_tableau(request, store, "download_workbook", ref, op)
    return Response(
        content=data,
        media_type="application/xml",
        headers={
            "X-Tableau-Workbook-Id": str(workbook.get("id") or ""),
            "X-Tableau-Workbook-Name": quote(str(workbook.get("name") or ""), safe=""),
        },
    )


@router.get("/workbooks/{ref:path}", dependencies=[RequireScope("execute")])
async def tableau_workbook(ref: str, request: Request, store: StoreD) -> dict[str, Any]:
    async def op(client: TableauClient) -> dict[str, Any]:
        return await tableau_content.workbook_details(client, ref)

    return await run_tableau(request, store, "get_workbook", ref, op)


@router.get("/datasources/{ref:path}/fields", dependencies=[RequireScope("execute")])
async def tableau_datasource_fields(ref: str, request: Request, store: StoreD) -> dict[str, Any]:
    async def op(client: TableauClient) -> dict[str, Any]:
        ds, fields = await tableau_vds.datasource_fields(client, ref)
        return {"datasource": {"id": ds.get("id"), "name": ds.get("name")}, "fields": fields}

    return await run_tableau(request, store, "datasource_fields", ref, op)


@router.post("/datasources/{ref:path}/query", dependencies=[RequireScope("execute")])
async def tableau_query_datasource(
    ref: str, body: DatasourceQueryBody, request: Request, store: StoreD
) -> dict[str, Any]:
    async def op(client: TableauClient) -> dict[str, Any]:
        return await tableau_vds.query_datasource(
            client, ref, fields=body.fields, filters=body.filters, limit=body.limit
        )

    return await run_tableau(request, store, "query_datasource", ref, op)


@router.get("/views/{ref:path}/image", dependencies=[RequireScope("execute")])
async def tableau_view_image(
    ref: str,
    request: Request,
    store: StoreD,
    width: int | None = Query(default=None, ge=100, le=10000),
    height: int | None = Query(default=None, ge=100, le=10000),
    max_age: int = Query(default=1, ge=1, le=240),
) -> Response:
    """PNG render of a view or dashboard (heavy dashboards take 30-120 s)."""

    async def op(client: TableauClient) -> tuple[dict[str, Any], bytes]:
        return await tableau_content.view_image(client, ref, width=width, height=height, max_age=max_age)

    view, png = await run_tableau(request, store, "view_image", ref, op)
    return Response(content=png, media_type="image/png", headers={"X-Tableau-View-Id": str(view.get("id") or "")})


@router.get("/views/{ref:path}/data", dependencies=[RequireScope("execute")])
async def tableau_view_data(
    ref: str,
    request: Request,
    store: StoreD,
    max_rows: int = Query(default=200, ge=1, le=10000),
) -> PlainTextResponse:
    """The view's summary data as CSV (header + at most ``max_rows`` rows)."""

    async def op(client: TableauClient) -> tuple[dict[str, Any], str]:
        return await tableau_content.view_data(client, ref, max_rows=max_rows)

    view, text = await run_tableau(request, store, "view_data", ref, op)
    return PlainTextResponse(
        content=text, media_type="text/csv", headers={"X-Tableau-View-Id": str(view.get("id") or "")}
    )


@router.get("/connections/{name}", dependencies=[RequireScope("execute")])
async def tableau_connection_info(name: str, request: Request, store: StoreD) -> dict[str, Any]:
    """Tableau-facing attributes of a SignalPilot connection. Never includes the password."""

    async def op(_client: TableauClient) -> dict[str, Any]:
        target = await connection_target(store, name)
        return target.public_dict()

    return await run_tableau(request, store, "connection_info", name, op)


@router.get("/projects", dependencies=[RequireScope("execute")])
async def tableau_projects(request: Request, store: StoreD) -> dict[str, Any]:
    async def op(client: TableauClient) -> dict[str, Any]:
        return {"projects": await tableau_content.list_projects(client)}

    return await run_tableau(request, store, "projects", None, op)
