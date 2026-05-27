# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from signalpilot._loggers import sp_logger

LOGGER = sp_logger()

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.applications import Starlette


@contextlib.asynccontextmanager
async def mcp_server_lifespan(app: Starlette) -> AsyncIterator[None]:
    """Lifespan for MCP server functionality (exposing sp as MCP server)."""

    try:
        mcp_app = app.state.mcp
        if mcp_app is None:
            LOGGER.warning("MCP server not found in app state")
            yield
            return

        # Session manager owns request lifecycle during app run
        async with mcp_app.session_manager.run():
            LOGGER.info("MCP server session manager started")
            yield

    except ImportError as e:
        LOGGER.warning(f"MCP server dependencies not available: {e}")
        yield
        return
    except Exception as e:
        LOGGER.error(f"Failed to start MCP server: {e}")
        yield
        return
