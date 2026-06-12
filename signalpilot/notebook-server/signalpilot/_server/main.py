from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from signalpilot import _loggers
from signalpilot._server.api.auth import (
    RANDOM_SECRET,
    CustomAuthenticationMiddleware,
    CustomSessionMiddleware,
    on_auth_error,
)
from signalpilot._server.api.middleware import (
    AuthBackend,
    OpenTelemetryMiddleware,
    ProxyMiddleware,
    SkewProtectionMiddleware,
    TimeoutMiddleware,
)
from signalpilot._server.api.router import build_routes
from signalpilot._server.errors import handle_error
from signalpilot._server.lsp import LspServer
from signalpilot._server.registry import MIDDLEWARE_REGISTRY
from signalpilot._utils.http import (
    HTTPException as SpHTTPException,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.types import Lifespan

LOGGER = _loggers.sp_logger()


@dataclass
class LspPorts:
    pylsp: int | None
    copilot: int | None


# Create app
def create_starlette_app(
    *,
    base_url: str,
    host: str | None = None,
    middleware: list[Middleware] | None = None,
    lifespan: Lifespan[Starlette] | None = None,
    enable_auth: bool = True,
    allow_origins: tuple[str, ...] | None = None,
    allow_credentials: bool = True,
    lsp_servers: list[LspServer] | None = None,
    skew_protection: bool = True,
    timeout: float | None = None,
) -> Starlette:
    final_middlewares: list[Middleware] = []

    if allow_origins is None:
        allow_origins = ("localhost", "127.0.0.1") + (
            (host,) if host is not None else ()
        )

    # The Fetch spec forbids Allow-Credentials: true with a wildcard origin;
    # browsers reject every credentialed response when the server does this.
    if allow_credentials and "*" in allow_origins:
        raise ValueError(
            "allow_origins may not contain '*' when allow_credentials=True. "
            "Specify explicit origins via SP_ALLOW_ORIGINS (run mode) or "
            "--allow-origins (edit mode), or set SP_ALLOW_CREDENTIALS=false "
            "to disable credentials (public read-only deployments only)."
        )

    if enable_auth:
        final_middlewares.extend(
            [
                Middleware(
                    CustomSessionMiddleware,
                    secret_key=RANDOM_SECRET,
                ),
            ]
        )

    final_middlewares.extend(
        [
            Middleware(OpenTelemetryMiddleware),
            Middleware(
                CustomAuthenticationMiddleware,
                backend=AuthBackend(should_authenticate=enable_auth),
                on_error=on_auth_error,
            ),
            Middleware(
                CORSMiddleware,
                allow_origins=allow_origins,
                allow_credentials=allow_credentials,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ]
    )

    if skew_protection:
        final_middlewares.append(Middleware(SkewProtectionMiddleware))

    if lsp_servers is not None:
        final_middlewares.extend(
            _create_lsps_proxy_middleware(
                base_url=base_url, servers=lsp_servers
            )
        )

    if middleware:
        final_middlewares.extend(middleware)

    final_middlewares.extend(MIDDLEWARE_REGISTRY.get_all())

    app = Starlette(
        routes=build_routes(base_url=base_url),
        middleware=final_middlewares,
        lifespan=lifespan,
        exception_handlers={
            Exception: handle_error,
            HTTPException: handle_error,
            SpHTTPException: handle_error,
            ModuleNotFoundError: handle_error,
        },
    )
    if timeout is not None:
        app.add_middleware(
            TimeoutMiddleware,
            app_state=app.state,
            timeout_duration_minutes=timeout,
        )
    return app


def _create_lsps_proxy_middleware(
    base_url: str, *, servers: list[LspServer]
) -> Iterator[Middleware]:
    return (
        Middleware(
            ProxyMiddleware,
            proxy_path=f"{base_url}/lsp/{server.id}",
            target_url=f"http://localhost:{server.port}",
        )
        for server in servers
    )
