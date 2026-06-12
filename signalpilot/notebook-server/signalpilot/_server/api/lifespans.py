from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from typing import TYPE_CHECKING, Any

from signalpilot import _loggers
from signalpilot._server.api.deps import AppState, AppStateBase
from signalpilot._server.api.interrupt import InterruptHandler
from signalpilot._server.api.utils import open_url_in_browser
from signalpilot._server.lsp import any_lsp_server_running
from signalpilot._server.print import (
    print_experimental_features,
    print_mcp_server,
    print_shutdown,
    print_startup,
)
from signalpilot._server.session_manager import SessionManager
from signalpilot._server.tokens import AuthToken
from signalpilot._server.utils import initialize_mimetypes
from signalpilot._server.uvicorn_utils import close_uvicorn
from signalpilot._server.workspace import NEW_FILE
from signalpilot._session.model import SessionMode
from signalpilot._utils.subprocess import cancel_pending_reaps

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette

LOGGER = _loggers.sp_logger()

background_tasks: set[asyncio.Task[Any]] = set()


@contextlib.asynccontextmanager
async def lsp(app: Starlette) -> AsyncIterator[None]:
    state = AppState.from_app(app)
    user_config = state.config_manager.get_config()
    session_mgr = state.session_manager

    # Only start the LSP server in Edit mode
    if session_mgr.mode != SessionMode.EDIT:
        yield
        return

    # Only start the LSP server if any LSP servers are configured
    if not any_lsp_server_running(user_config):
        yield
        return

    LOGGER.debug("Language Servers are enabled")
    # Start LSP server in background to avoid blocking server startup
    task = asyncio.create_task(session_mgr.start_lsp_server())
    background_tasks.add(task)  # Keep a reference to prevent GC
    task.add_done_callback(background_tasks.discard)  # Clean up when done

    yield

    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@contextlib.asynccontextmanager
async def open_browser(app: Starlette) -> AsyncIterator[None]:
    state = AppState.from_app(app)
    if not state.headless:
        url = _startup_url(state)
        user_config = state.config_manager.get_config()
        browser = user_config["server"]["browser"]
        # Wait 20ms for the server to start and then open the browser, but this
        # function must complete
        asyncio.get_running_loop().call_later(
            0.02, open_url_in_browser, browser, url
        )
    yield


@contextlib.asynccontextmanager
async def logging(app: Starlette) -> AsyncIterator[None]:
    state = AppState.from_app(app)
    manager: SessionManager = state.session_manager
    quiet = state.quiet
    workspace = manager.workspace
    mcp_server_enabled = state.mcp_server_enabled
    skew_protection_enabled = state.skew_protection

    # Startup message
    if not quiet:
        file = workspace.single_file()
        print_startup(
            file_name=file.name if file else None,
            url=_startup_url(state),
            run=manager.mode == SessionMode.RUN,
            new=workspace.get_unique_file_key() == NEW_FILE,
            network=state.host == "0.0.0.0",
            startup_tip=state.startup_tip,
        )

        print_experimental_features(state.config_manager.get_config())

        if mcp_server_enabled:
            mcp_url = _mcp_startup_url(state)
            server_token = None
            if skew_protection_enabled:
                server_token = str(state.session_manager.skew_protection_token)
            print_mcp_server(mcp_url, server_token)

    yield

    # Shutdown message
    if not quiet:
        print_shutdown()


@contextlib.asynccontextmanager
async def signal_handler(app: Starlette) -> AsyncIterator[None]:
    state = AppState.from_app(app)
    manager = state.session_manager

    # Interrupt handler
    def shutdown() -> None:
        manager.shutdown()
        if state.server:
            close_uvicorn(state.server)

    InterruptHandler(
        quiet=state.quiet,
        shutdown=shutdown,
    ).register()
    yield


@contextlib.asynccontextmanager
async def server_registry(app: Starlette) -> AsyncIterator[None]:
    """Register this server in the local registry for discovery.

    Only servers started **without** an auth token (``--no-token``)
    are registered.  This ensures only servers that have explicitly
    opted into relaxed local access are discoverable.
    """
    from signalpilot._server.server_registry import (
        ServerRegistryEntry,
        ServerRegistryWriter,
    )

    state = AppState.from_app(app)

    # Guard: only register when the user has opted into relaxed local
    # access (no auth token).  Skew protection is irrelevant here —
    # it guards against frontend/server version mismatch and should
    # not prevent agent-oriented discovery.
    if state.enable_auth:
        LOGGER.debug(
            "Skipping server registry: auth=%s",
            state.enable_auth,
        )
        yield
        return

    entry = ServerRegistryEntry.from_server(
        host=state.host,
        port=state.port,
        base_url=state.base_url,
    )
    writer = ServerRegistryWriter(entry)
    try:
        writer.register()
    except Exception as e:
        LOGGER.warning("Failed to register server: %s", e)

    yield

    writer.deregister()


@contextlib.asynccontextmanager
async def kernel_warmup(app: Starlette) -> AsyncIterator[None]:
    """Pre-warm kernel infrastructure for fast EDIT-mode startup.

    Eagerly imports heavy modules (benefits forkserver on Linux and
    filesystem cache everywhere). Configures forkserver preload on the
    main thread before any kernel processes are created.
    """
    state = AppState.from_app(app)
    manager: SessionManager = state.session_manager

    if manager.mode == SessionMode.EDIT:
        from signalpilot._session.managers._mp_context import configure_forkserver
        from signalpilot._session.managers.warmup import preload_kernel_modules

        configure_forkserver()
        preload_kernel_modules()
        LOGGER.debug("Kernel pre-warming complete")

    yield


@contextlib.asynccontextmanager
async def etc(app: Starlette) -> AsyncIterator[None]:
    del app
    # Mimetypes
    initialize_mimetypes()
    yield


@contextlib.asynccontextmanager
async def reap_subprocesses(app: Starlette) -> AsyncIterator[None]:
    del app
    yield
    await cancel_pending_reaps()


def _pretty_host(host: str, port: int) -> str:
    """Replace loopback addresses with 'localhost' for display.

    Uses ipaddress for a reliable cross-platform loopback check (covers
    127.0.0.1, ::1, and the full 127.0.0.0/8 range).  Falls back to
    socket.getnameinfo only for non-IP hosts.  getnameinfo is skipped for
    raw IP addresses because it can hang on Windows/CI for link-local IPv6.
    """
    try:
        if ipaddress.ip_address(host).is_loopback:
            return "localhost"
    except ValueError:
        # Not a valid IP literal — might be a hostname; try getnameinfo
        try:
            if (
                socket.getnameinfo((host, port), socket.NI_NOFQDN)[0]
                == "localhost"
            ):
                return "localhost"
        except Exception:
            pass
    return host


def _startup_url(state: AppStateBase) -> str:
    host = state.host.strip(
        "[]"
    )  # normalize: remove brackets if user passed [addr]
    port = state.port

    # Strip IPv6 zone ID (e.g. fe80::1%eth0 -> fe80::1); zone IDs are
    # interface-specific and not valid in URLs.
    # Must happen before _pretty_host — zone IDs can cause getnameinfo
    # to hang on Windows/CI.
    host = host.split("%")[0]

    # pretty printing: show "localhost" for loopback addresses
    host = _pretty_host(host, port)

    url_host_bare = host
    # IPv6 addresses must be wrapped in brackets in URLs (RFC 3986)
    url_host = f"[{url_host_bare}]" if ":" in url_host_bare else url_host_bare
    url = f"http://{url_host}:{port}{state.base_url}"
    if port == 80:
        url = f"http://{url_host}{state.base_url}"
    elif port == 443:
        url = f"https://{url_host}{state.base_url}"

    if AuthToken.is_empty(state.session_manager.auth_token):
        return url
    return f"{url}?access_token={state.session_manager.auth_token!s}"


def _mcp_startup_url(state: AppStateBase) -> str:
    host = state.host.strip(
        "[]"
    )  # normalize: remove brackets if user passed [addr]
    port = state.port
    base_url = state.base_url

    # Strip zone ID, then pretty-print loopback (same logic as _startup_url)
    host = host.split("%")[0]
    host = _pretty_host(host, port)

    url_host_bare = host
    url_host = f"[{url_host_bare}]" if ":" in url_host_bare else url_host_bare
    # Construct MCP endpoint URL
    mcp_prefix = "/mcp"
    mcp_name = "server"
    full_mcp_path = f"{mcp_prefix}/{mcp_name}"
    url = f"http://{url_host}:{port}{base_url}{full_mcp_path}"
    if port == 80:
        url = f"http://{url_host}{base_url}{full_mcp_path}"
    elif port == 443:
        url = f"https://{url_host}{base_url}{full_mcp_path}"

    # Add access token if not empty
    if AuthToken.is_empty(state.session_manager.auth_token):
        return url
    return f"{url}?access_token={state.session_manager.auth_token!s}"
