"""OAuth discovery documents for the gateway MCP endpoint.

Served publicly (no credentials) so MCP clients can find the authorization
server after a ``401`` from ``/mcp``:

* ``/.well-known/oauth-protected-resource/mcp`` — RFC 9728 §3.1 path-suffixed
  document for the ``/mcp`` resource (what the ``WWW-Authenticate`` challenge
  points at).
* ``/.well-known/oauth-protected-resource`` — root fallback probed by clients
  that predate the path-suffixed form.
* ``/.well-known/oauth-authorization-server`` and
  ``/.well-known/openid-configuration`` — Clerk's authorization-server
  metadata mirrored on this origin for clients that look it up on the MCP
  host instead of following ``authorization_servers``.

All routes answer ``404`` when OAuth is off (local mode / Clerk unset).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from ..auth.mcp_oauth import clerk_frontend_api, oauth_enabled, protected_resource_metadata

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth-metadata"])

WELL_KNOWN_PREFIX = "/.well-known/"

_AS_METADATA_TTL_SECONDS = 300.0
_as_metadata_cache: dict[str, tuple[dict[str, Any], float]] = {}

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "mcp-protocol-version, content-type",
    "Cache-Control": "public, max-age=300",
}


def _require_enabled() -> None:
    if not oauth_enabled():
        raise HTTPException(status_code=404, detail="Not Found")


def _json(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(payload, headers=_CORS_HEADERS)


@router.options("/.well-known/{rest:path}", include_in_schema=False)
async def well_known_preflight(rest: str) -> Response:
    _require_enabled()
    return Response(status_code=204, headers=_CORS_HEADERS)


@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
async def protected_resource() -> JSONResponse:
    """RFC 9728 protected-resource metadata pointing at Clerk."""
    _require_enabled()
    return _json(protected_resource_metadata())


async def fetch_authorization_server_metadata(document: str) -> dict[str, Any]:
    """Fetch (and briefly cache) Clerk's RFC 8414 / OIDC discovery document."""
    issuer = clerk_frontend_api()
    if not issuer:
        raise HTTPException(status_code=404, detail="Not Found")
    url = f"{issuer}/.well-known/{document}"
    cached = _as_metadata_cache.get(url)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.error("OAuth metadata: cannot reach %s: %s", url, exc)
        raise HTTPException(status_code=503, detail="Authorization server metadata unavailable")
    if resp.status_code != 200:
        raise HTTPException(status_code=503, detail="Authorization server metadata unavailable")
    payload = resp.json()
    _as_metadata_cache[url] = (payload, time.monotonic() + _AS_METADATA_TTL_SECONDS)
    return payload


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def authorization_server() -> JSONResponse:
    _require_enabled()
    return _json(await fetch_authorization_server_metadata("oauth-authorization-server"))


@router.get("/.well-known/openid-configuration", include_in_schema=False)
async def openid_configuration() -> JSONResponse:
    _require_enabled()
    return _json(await fetch_authorization_server_metadata("openid-configuration"))
