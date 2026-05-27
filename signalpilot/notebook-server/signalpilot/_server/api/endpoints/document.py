# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.authentication import requires

from signalpilot._messaging.notebook.changes import Transaction
from signalpilot._messaging.notification import (
    NotebookDocumentTransactionNotification,
)
from signalpilot._server.api.deps import AppState
from signalpilot._server.api.utils import parse_request
from signalpilot._server.models.models import (
    BaseResponse,
    NotebookDocumentTransactionRequest,
    SuccessResponse,
)
from signalpilot._server.router import APIRouter
from signalpilot._types.ids import ConsumerId

if TYPE_CHECKING:
    from starlette.requests import Request

router = APIRouter()


@router.post("/transaction")
@requires("edit")
async def document_transaction(request: Request) -> BaseResponse:
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
                    $ref: "#/components/schemas/NotebookDocumentTransactionRequest"
    responses:
        200:
            description: Apply a document transaction
            content:
                application/json:
                    schema:
                        $ref: "#/components/schemas/SuccessResponse"
    """
    app_state = AppState(request)
    body = await parse_request(request, cls=NotebookDocumentTransactionRequest)
    session = app_state.require_current_session()
    session_id = app_state.require_current_session_id()

    transaction = Transaction(changes=tuple(body.changes), source="frontend")
    applied = session.document.apply(transaction)
    session.notify(
        NotebookDocumentTransactionNotification(transaction=applied),
        from_consumer_id=ConsumerId(session_id),
    )

    return SuccessResponse()
