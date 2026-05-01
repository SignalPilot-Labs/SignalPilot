"""Typed exceptions and FastAPI error handlers for the Workspaces API."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class WorkspacesError(Exception):
    """Base class for all Workspaces domain errors."""

    error_code: str = "workspaces_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InferenceNotConfigured(WorkspacesError):
    """Raised when no valid inference source is available for the request."""

    error_code = "inference_not_configured"


class MeteredNotImplemented(WorkspacesError):
    """Raised when metered inference is requested but not yet implemented (R3+)."""

    error_code = "metered_not_implemented"


class IllegalTransition(WorkspacesError):
    """Raised when a run state transition is not permitted."""

    error_code = "illegal_transition"


class RunNotFound(WorkspacesError):
    """Raised when a run cannot be found by ID."""

    error_code = "run_not_found"


class ApprovalNotFound(WorkspacesError):
    """Raised when an approval record cannot be found."""

    error_code = "approval_not_found"


class ChartNotFound(WorkspacesError):
    """Raised when a chart cannot be found by ID."""

    error_code = "chart_not_found"


class ChartCacheCorrupt(WorkspacesError):
    """Raised when the chart cache row contains unparseable JSON."""

    error_code = "chart_cache_corrupt"


class SpawnFailed(WorkspacesError):
    """Raised when subprocess spawn or workdir setup fails unexpectedly."""

    error_code = "spawn_failed"


class ProxyTokenMintFailed(WorkspacesError):
    """Raised when minting a gateway dbt-proxy run-token fails.

    error_code sub-codes: "auth", "conflict", "missing_api_key".
    """

    error_code = "proxy_token_mint_failed"


class SandboxBinaryNotFound(WorkspacesError):
    """Raised at startup when the sandbox server.py path does not exist."""

    error_code = "sandbox_binary_not_found"


def _error_body(exc: WorkspacesError) -> dict[str, str]:
    return {"error_code": exc.error_code, "message": exc.message}


def register_exception_handlers(app: FastAPI) -> None:
    """Register all domain exception handlers on the FastAPI app."""

    @app.exception_handler(InferenceNotConfigured)
    async def _inference_not_configured(
        request: Request, exc: InferenceNotConfigured
    ) -> JSONResponse:
        logger.warning("inference_not_configured: %s", exc.message)
        return JSONResponse(status_code=422, content=_error_body(exc))

    @app.exception_handler(MeteredNotImplemented)
    async def _metered_not_implemented(
        request: Request, exc: MeteredNotImplemented
    ) -> JSONResponse:
        logger.warning("metered_not_implemented: %s", exc.message)
        return JSONResponse(status_code=501, content=_error_body(exc))

    @app.exception_handler(IllegalTransition)
    async def _illegal_transition(
        request: Request, exc: IllegalTransition
    ) -> JSONResponse:
        logger.warning("illegal_transition: %s", exc.message)
        return JSONResponse(status_code=409, content=_error_body(exc))

    @app.exception_handler(RunNotFound)
    async def _run_not_found(request: Request, exc: RunNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_error_body(exc))

    @app.exception_handler(ApprovalNotFound)
    async def _approval_not_found(
        request: Request, exc: ApprovalNotFound
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content=_error_body(exc))

    @app.exception_handler(ChartNotFound)
    async def _chart_not_found(request: Request, exc: ChartNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_error_body(exc))

    @app.exception_handler(ChartCacheCorrupt)
    async def _chart_cache_corrupt(request: Request, exc: ChartCacheCorrupt) -> JSONResponse:
        logger.error("chart_cache_corrupt: %s", exc.message)
        return JSONResponse(status_code=500, content=_error_body(exc))

    @app.exception_handler(SpawnFailed)
    async def _spawn_failed(request: Request, exc: SpawnFailed) -> JSONResponse:
        logger.error("spawn_failed: %s", exc.message)
        return JSONResponse(status_code=500, content=_error_body(exc))

    @app.exception_handler(ProxyTokenMintFailed)
    async def _proxy_token_mint_failed(
        request: Request, exc: ProxyTokenMintFailed
    ) -> JSONResponse:
        logger.error("proxy_token_mint_failed: %s", exc.message)
        return JSONResponse(status_code=502, content=_error_body(exc))

    @app.exception_handler(SandboxBinaryNotFound)
    async def _sandbox_binary_not_found(
        request: Request, exc: SandboxBinaryNotFound
    ) -> JSONResponse:
        logger.error("sandbox_binary_not_found: %s", exc.message)
        return JSONResponse(status_code=503, content=_error_body(exc))
