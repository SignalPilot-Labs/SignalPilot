"""Health check and local auth endpoints — public, no user data."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..runtime.mode import is_cloud_mode

router = APIRouter()


@router.get("/health")
async def health():
    if is_cloud_mode():
        from ..store.tls_migration import check_plaintext_tls_readiness

        blocked = await check_plaintext_tls_readiness()
        if blocked:
            return JSONResponse(
                {"status": "not_ready", "reason": "legacy_plaintext_tls_config", "detail": blocked},
                status_code=503,
            )
    return {"status": "healthy", "version": "0.1.0"}


@router.get("/local-api-key")
async def local_api_key(request: Request):
    """Return the local API key for dev tooling.

    Only available in local mode. Returns 404 in cloud mode.
    The key is the same one used by the web container and notebook
    to authenticate with the gateway.
    """
    if is_cloud_mode():
        return JSONResponse({"error": "Not available in cloud mode"}, status_code=404)

    from ..store import get_local_api_key
    key = get_local_api_key()
    return {"key": key}
