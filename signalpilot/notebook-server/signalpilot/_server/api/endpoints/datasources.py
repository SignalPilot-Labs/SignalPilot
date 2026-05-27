# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.authentication import requires
from starlette.responses import Response

from signalpilot import _loggers
from signalpilot._server.api.utils import dispatch_control_request
from signalpilot._server.models.models import (
    BaseResponse,
    ListDataSourceConnectionRequest,
    ListSQLSchemasRequest,
    ListSQLTablesRequest,
    PreviewDatasetColumnRequest,
    PreviewSQLTableRequest,
)
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

LOGGER = _loggers.sp_logger()

# Router for data source endpoints
router = APIRouter()


@router.get("/gateway_connections")
async def gateway_connections(*, request: Request) -> Response:
    """List SignalPilot Gateway database connections.

    Does NOT require an active notebook session — works at any time.
    Returns the same connection format the kernel broadcasts after first cell run.
    """
    try:
        from signalpilot._gateway import get_gateway_client
        from signalpilot._gateway.adapters import gateway_connection_to_datasource

        client = get_gateway_client()
        if client is None:
            return Response(
                content=json.dumps({"connections": [], "error": "Gateway not configured (SP_API_KEY not set)"}),
                media_type="application/json",
            )

        connections = client.list_connections()
        datasources = []
        for conn in connections:
            conn_name = conn.get("name", "")
            try:
                schema_data = client.get_schema(conn_name)
                ds = gateway_connection_to_datasource(conn, schema_data)
            except Exception:
                ds = gateway_connection_to_datasource(conn)
            datasources.append(ds)

        import msgspec
        return Response(
            content=msgspec.json.encode({"connections": datasources}),
            media_type="application/json",
        )
    except Exception as e:
        LOGGER.warning(f"Failed to fetch gateway connections: {e}")
        return Response(
            content=json.dumps({"connections": [], "error": str(e)}),
            media_type="application/json",
        )


@router.post("/preview_column")
@requires("edit")
async def preview_column(
    request: Request,
) -> BaseResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/PreviewDatasetColumnRequest"
    responses:
        200:
            description: Preview a column in a dataset
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(request, PreviewDatasetColumnRequest)


@router.post("/preview_sql_table")
@requires("edit")
async def preview_sql_table(request: Request) -> BaseResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/PreviewSQLTableRequest"
    responses:
        200:
            description: Preview a SQL table
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(request, PreviewSQLTableRequest)


@router.post("/preview_sql_table_list")
@requires("edit")
async def preview_sql_table_list(request: Request) -> BaseResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/ListSQLTablesRequest"
    responses:
        200:
            description: Preview a list of tables in an SQL schema
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(request, ListSQLTablesRequest)


@router.post("/preview_sql_schema_list")
@requires("edit")
async def preview_sql_schema_list(request: Request) -> BaseResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/ListSQLSchemasRequest"
    responses:
        200:
            description: Preview a list of schemas in an SQL database
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(request, ListSQLSchemasRequest)


@router.post("/preview_datasource_connection")
@requires("edit")
async def preview_datasource_connection(request: Request) -> BaseResponse:
    """
    parameters:
        - in: header
          name: Sp-Session-Id
          schema:
            type: string
          required: true
    requestBody:
        content:
            application/json:
                schema:
                    $ref: "#/components/schemas/ListDataSourceConnectionRequest"
    responses:
        200:
            description: Broadcasts a datasource connection
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    return await dispatch_control_request(
        request, ListDataSourceConnectionRequest
    )
