"""Typed exceptions and FastAPI error handlers for the Workspaces API.

H1 error contract (R5):
  WorkspacesError subclasses emit {error_code, correlation_id} bodies only.
  No message field is included in any WorkspacesError handler response.
  Full detail is written to structured logs only.

Carve-out: HTTPException(detail=...)-based 4xx responses (e.g. approval
  illegal_transition via routes/runs.py) use FastAPI's default handler and
  retain their existing {error_code, message} shape. These don't carry
  credential-bearing reprs so H1 hardening is out-of-scope for them.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class WorkspacesError(Exception):
    """Base class for all Workspaces domain errors."""

    error_code: str = "workspaces_error"

    def __init__(self, message: str, *, correlation_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.correlation_id = correlation_id


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


class ConnectorRequiresHostNet(SpawnFailed):
    """Raised when a connector spawn is requested under a sandbox runtime.

    Connector runs need loopback TCP access to the dbt-proxy (127.0.0.1),
    which is not available inside the gVisor netns. This guard fires at spawn
    time instead of letting the run silently fail at DB-connect time.

    R9 will lift this guard once --net=host (or socket-passing) lands.
    """

    error_code = "connector_requires_host_net"


class ProxyTokenMintFailed(WorkspacesError):
    """Raised when minting a gateway dbt-proxy run-token fails.

    error_code sub-codes: "auth", "conflict", "missing_api_key".
    """

    error_code = "proxy_token_mint_failed"


class SandboxBinaryNotFound(WorkspacesError):
    """Raised at startup when the sandbox server.py path does not exist."""

    error_code = "sandbox_binary_not_found"


class SandboxRuntimeUnavailable(WorkspacesError):
    """Raised at startup when the configured sandbox runtime binary is missing or broken,
    or when cloud mode is configured without a sandbox runtime."""

    error_code = "sandbox_runtime_unavailable"


class AuthMissingToken(WorkspacesError):
    """Raised when the Authorization header is absent or malformed."""

    error_code = "auth_missing_token"


class AuthInvalidToken(WorkspacesError):
    """Raised when JWT verification fails (bad signature, expired, wrong issuer/audience,
    unknown kid, kty/alg mismatch).

    The agent-facing response body contains only error_code + correlation_id.
    Full failure details are logged with correlation_id only.
    """

    error_code = "auth_invalid_token"


class ClerkJWKSUnavailable(WorkspacesError):
    """Raised when the Clerk JWKS endpoint is unreachable or returns non-2xx.

    Mapped to 503 — do not return 401 for upstream JWKS outages.
    The distinction matters: 401 tells the client "your token is bad",
    503 tells the client "our gateway is temporarily down".
    """

    error_code = "clerk_jwks_unavailable"


class ClerkConfigMissing(WorkspacesError):
    """Raised at startup when cloud mode is enabled but Clerk settings are absent."""

    error_code = "clerk_config_missing"


def _resolve_correlation_id(exc: WorkspacesError) -> str:
    """Return exc.correlation_id, or generate one if absent."""
    if exc.correlation_id is not None:
        return exc.correlation_id
    return uuid.uuid4().hex[:16]


def _error_body(exc: WorkspacesError, correlation_id: str) -> dict[str, str]:
    return {"error_code": exc.error_code, "correlation_id": correlation_id}


def register_exception_handlers(app: FastAPI) -> None:
    """Register all domain exception handlers on the FastAPI app."""

    @app.exception_handler(InferenceNotConfigured)
    async def _inference_not_configured(
        request: Request, exc: InferenceNotConfigured
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.warning(
            "inference_not_configured cid=%s detail=%s", cid, exc.message
        )
        return JSONResponse(status_code=422, content=_error_body(exc, cid))

    @app.exception_handler(MeteredNotImplemented)
    async def _metered_not_implemented(
        request: Request, exc: MeteredNotImplemented
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.warning(
            "metered_not_implemented cid=%s detail=%s", cid, exc.message
        )
        return JSONResponse(status_code=501, content=_error_body(exc, cid))

    @app.exception_handler(IllegalTransition)
    async def _illegal_transition(
        request: Request, exc: IllegalTransition
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.warning("illegal_transition cid=%s detail=%s", cid, exc.message)
        return JSONResponse(status_code=409, content=_error_body(exc, cid))

    @app.exception_handler(RunNotFound)
    async def _run_not_found(request: Request, exc: RunNotFound) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        return JSONResponse(status_code=404, content=_error_body(exc, cid))

    @app.exception_handler(ApprovalNotFound)
    async def _approval_not_found(
        request: Request, exc: ApprovalNotFound
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        return JSONResponse(status_code=404, content=_error_body(exc, cid))

    @app.exception_handler(ChartNotFound)
    async def _chart_not_found(request: Request, exc: ChartNotFound) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        return JSONResponse(status_code=404, content=_error_body(exc, cid))

    @app.exception_handler(ChartCacheCorrupt)
    async def _chart_cache_corrupt(
        request: Request, exc: ChartCacheCorrupt
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error(
            "chart_cache_corrupt cid=%s detail=%s", cid, exc.message
        )
        return JSONResponse(status_code=500, content=_error_body(exc, cid))

    @app.exception_handler(ConnectorRequiresHostNet)
    async def _connector_requires_host_net(
        request: Request, exc: ConnectorRequiresHostNet
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.warning(
            "connector_requires_host_net cid=%s detail=%s", cid, exc.message
        )
        return JSONResponse(status_code=409, content=_error_body(exc, cid))

    @app.exception_handler(SpawnFailed)
    async def _spawn_failed(request: Request, exc: SpawnFailed) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error(
            "spawn_failed cid=%s detail=%s", cid, exc.message,
            extra={"correlation_id": cid, "detail": exc.message},
        )
        return JSONResponse(status_code=500, content=_error_body(exc, cid))

    @app.exception_handler(ProxyTokenMintFailed)
    async def _proxy_token_mint_failed(
        request: Request, exc: ProxyTokenMintFailed
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error(
            "proxy_token_mint_failed cid=%s detail=%s", cid, exc.message,
            extra={"correlation_id": cid, "detail": exc.message},
        )
        return JSONResponse(status_code=502, content=_error_body(exc, cid))

    @app.exception_handler(SandboxBinaryNotFound)
    async def _sandbox_binary_not_found(
        request: Request, exc: SandboxBinaryNotFound
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error(
            "sandbox_binary_not_found cid=%s detail=%s", cid, exc.message
        )
        return JSONResponse(status_code=503, content=_error_body(exc, cid))

    @app.exception_handler(SandboxRuntimeUnavailable)
    async def _sandbox_runtime_unavailable(
        request: Request, exc: SandboxRuntimeUnavailable
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error(
            "sandbox_runtime_unavailable cid=%s detail=%s", cid, exc.message
        )
        return JSONResponse(status_code=503, content=_error_body(exc, cid))

    # R6: auth error handlers
    @app.exception_handler(AuthMissingToken)
    async def _auth_missing_token(
        request: Request, exc: AuthMissingToken
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.warning("auth_missing_token cid=%s", cid)
        return JSONResponse(status_code=401, content=_error_body(exc, cid))

    @app.exception_handler(AuthInvalidToken)
    async def _auth_invalid_token(
        request: Request, exc: AuthInvalidToken
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        # Log full detail (reason for rejection) but return only generic body.
        logger.warning("auth_invalid_token cid=%s detail=%s", cid, exc.message)
        return JSONResponse(status_code=401, content=_error_body(exc, cid))

    @app.exception_handler(ClerkJWKSUnavailable)
    async def _clerk_jwks_unavailable(
        request: Request, exc: ClerkJWKSUnavailable
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error("clerk_jwks_unavailable cid=%s detail=%s", cid, exc.message)
        return JSONResponse(status_code=503, content=_error_body(exc, cid))

    @app.exception_handler(ClerkConfigMissing)
    async def _clerk_config_missing(
        request: Request, exc: ClerkConfigMissing
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error("clerk_config_missing cid=%s detail=%s", cid, exc.message)
        return JSONResponse(status_code=503, content=_error_body(exc, cid))

    # R5: chart execution error handlers
    from workspaces_api.dashboards.errors import (
        ChartExecutionFailed,
        ChartExecutionTimeout,
    )

    @app.exception_handler(ChartExecutionFailed)
    async def _chart_execution_failed(
        request: Request, exc: ChartExecutionFailed
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error(
            "chart_execution_failed cid=%s detail=%s", cid, exc.message,
            extra={"correlation_id": cid, "detail": exc.message},
        )
        return JSONResponse(status_code=502, content=_error_body(exc, cid))

    @app.exception_handler(ChartExecutionTimeout)
    async def _chart_execution_timeout(
        request: Request, exc: ChartExecutionTimeout
    ) -> JSONResponse:
        cid = _resolve_correlation_id(exc)
        logger.error(
            "chart_execution_timeout cid=%s detail=%s", cid, exc.message,
            extra={"correlation_id": cid, "detail": exc.message},
        )
        return JSONResponse(status_code=504, content=_error_body(exc, cid))
