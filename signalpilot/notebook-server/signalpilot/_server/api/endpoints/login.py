from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlparse

from starlette.authentication import requires
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from signalpilot._server.api.auth import validate_auth
from signalpilot._server.api.deps import AppState
from signalpilot._server.router import APIRouter

if TYPE_CHECKING:
    from starlette.requests import Request

router = APIRouter()

_LOGIN_TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent / "templates" / "login.html"
)
_LOGIN_TEMPLATE = _LOGIN_TEMPLATE_PATH.read_text(encoding="utf-8")

_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}


def _validate_redirect(
    redirect_url: str,
    request: Request,
    base_url: str,
) -> str:
    """Validate redirect URL to prevent open redirect vulnerabilities.

    Rejects protocol-relative URLs (e.g. //evil.com) which browsers
    interpret as absolute URLs, bypassing scheme-based checks.
    """
    parsed = urlparse(redirect_url)
    if parsed.netloc and parsed.netloc != request.url.netloc:
        return base_url
    return redirect_url


@router.get("/login", name="login_page")
async def login_page(request: Request) -> Response:
    """
    tags: [auth]
    summary: Login page
    responses:
        200:
            description: Renders the login form
            content:
                text/html:
                    schema:
                        type: string
        302:
            description: Redirect when already authenticated
            headers:
                Location:
                    schema:
                        type: string
    """
    base_url = _with_trailing_slash(AppState(request).base_url or "/")
    redirect_url = request.query_params.get("next", base_url)
    redirect_url = _validate_redirect(redirect_url, request, base_url)

    if request.user.is_authenticated:
        return RedirectResponse(redirect_url, 302, headers=_SECURITY_HEADERS)

    rendered = _LOGIN_TEMPLATE.format(
        base_url=html.escape(base_url, quote=True),
        next=html.escape(redirect_url, quote=True),
        success_url=html.escape(redirect_url, quote=True),
    )
    return HTMLResponse(rendered, headers=_SECURITY_HEADERS)


@router.post("/login")
async def login_submit(request: Request) -> Response:
    """
    tags: [auth]
    summary: Submit login form
    requestBody:
        content:
            application/x-www-form-urlencoded:
                schema:
                    type: object
                    properties:
                        password:
                            type: string
                            description: Access token or password
                        next:
                            type: string
                            description: Redirect URL after successful login
    responses:
        302:
            description: Redirect to the next URL
            headers:
                Location:
                    schema:
                        type: string
        401:
            description: Invalid or missing password
            content:
                application/json:
                    schema:
                        type: object
                        properties:
                            error:
                                type: string
                        required: [error]
    """
    base_url = _with_trailing_slash(AppState(request).base_url or "/")

    body = (await request.body()).decode()
    data = dict(parse_qsl(body))
    password = data.get("password", "")

    next_from_body = data.get("next")
    next_from_query = request.query_params.get("next")
    raw_redirect = next_from_body or next_from_query or base_url
    redirect_url = _validate_redirect(raw_redirect, request, base_url)

    if not password:
        return JSONResponse(
            {"error": "Password is required"},
            status_code=401,
            headers=_SECURITY_HEADERS,
        )

    success = validate_auth(request, data)
    if success:
        return RedirectResponse(redirect_url, 302, headers=_SECURITY_HEADERS)

    return JSONResponse(
        {"error": "Invalid password"},
        status_code=401,
        headers=_SECURITY_HEADERS,
    )


@router.get("/token")
@requires("edit")
async def auth_token(request: Request) -> JSONResponse:
    """
    tags: [auth]
    summary: Get the auth token for the current session
    responses:
        200:
            description: The auth token (null if auth is disabled)
            content:
                application/json:
                    schema:
                        type: object
                        properties:
                            token:
                                type: string
                                nullable: true
    """
    state = AppState(request)
    no_cache = {"Cache-Control": "no-store"}
    if not state.enable_auth:
        return JSONResponse({"token": None}, headers=no_cache)
    return JSONResponse(
        {"token": str(state.session_manager.auth_token)}, headers=no_cache
    )


def _with_trailing_slash(url: str) -> str:
    if not url.endswith("/"):
        return url + "/"
    return url
