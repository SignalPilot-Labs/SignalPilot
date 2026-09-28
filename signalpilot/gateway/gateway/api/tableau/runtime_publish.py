"""Tableau runtime publish routes: workbooks (multipart) and live datasources (JSON).

Warehouse credentials come from the SignalPilot connection and go straight
to Tableau; they never appear in a response or a log line.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, model_validator

from ...security.scope_guard import RequireScope
from ...tableau import publish as tableau_publish
from ...tableau.client import TableauClient
from ...tableau.connections import connection_target
from ..deps import StoreD
from .common import require_run_token, run_tableau

router = APIRouter(prefix="/api/tableau/runtime")

_TRUE = {"1", "true", "yes", "on"}


def _flag(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in _TRUE


class DatasourcePublishBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    connection: str = Field(min_length=1, max_length=255)
    database: str | None = Field(default=None, max_length=255)
    schema_: str | None = Field(default=None, alias="schema", max_length=255)
    table: str | None = Field(default=None, max_length=255)
    sql: str | None = Field(default=None, max_length=200_000)
    project: str | None = Field(default=None, max_length=255)
    overwrite: bool = True
    description: str | None = Field(default=None, max_length=4000)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _one_source(self) -> DatasourcePublishBody:
        if bool((self.table or "").strip()) == bool((self.sql or "").strip()):
            raise ValueError("Give exactly one of table or sql")
        return self


@router.post("/workbooks", dependencies=[RequireScope("execute")])
async def tableau_publish_workbook(
    request: Request,
    store: StoreD,
    file: UploadFile = File(...),
    name: str = Form(...),
    project: str | None = Form(default=None),
    overwrite: str | None = Form(default=None),
    connection: str | None = Form(default=None),
    show_tabs: str | None = Form(default=None),
    description: str | None = Form(default=None),
) -> dict[str, Any]:
    """Publish a .twb/.twbx, then embed the SignalPilot connection's credentials.

    ``connection`` defaults to the run's own connection. Only workbook
    connections on that connection's host receive credentials; the rest come
    back in ``unbound_connections``.
    """
    require_run_token(request)
    data = await file.read(tableau_publish.MAX_SINGLE_PUBLISH_BYTES + 1)
    if len(data) > tableau_publish.MAX_SINGLE_PUBLISH_BYTES:
        raise HTTPException(status_code=413, detail="Workbooks over 64 MB are not supported yet")
    filename = (file.filename or "").lower()
    if filename and not filename.endswith((".twb", ".twbx")):
        raise HTTPException(status_code=400, detail="The file must be a .twb or .twbx workbook")
    connection_name = (connection or "").strip() or store.allowed_connection_name

    async def op(client: TableauClient) -> dict[str, Any]:
        target = await connection_target(store, connection_name) if connection_name else None
        return await tableau_publish.publish_workbook(
            client,
            data=data,
            name=name,
            project=(project or "").strip() or None,
            overwrite=_flag(overwrite, True),
            show_tabs=_flag(show_tabs, True),
            description=(description or "").strip() or None,
            target=target,
        )

    return await run_tableau(request, store, "publish_workbook", name, op)


@router.post("/datasources", dependencies=[RequireScope("execute")])
async def tableau_publish_datasource(body: DatasourcePublishBody, request: Request, store: StoreD) -> dict[str, Any]:
    """Publish a live datasource on one table or SQL query of a SignalPilot connection."""

    async def op(client: TableauClient) -> dict[str, Any]:
        target = await connection_target(store, body.connection)
        target.require_supported()
        return await tableau_publish.publish_datasource(
            client,
            target=target,
            name=body.name,
            database=body.database,
            schema=body.schema_,
            table=(body.table or "").strip() or None,
            sql=(body.sql or "").strip() or None,
            project=body.project,
            overwrite=body.overwrite,
            description=body.description,
        )

    return await run_tableau(request, store, "publish_datasource", body.name, op)
